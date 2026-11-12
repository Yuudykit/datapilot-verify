from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from datapilot_verify.data.tables import execute_table_plan
from datapilot_verify.domain.models import (
    ArtifactRef,
    ErrorCode,
    EvidenceRef,
    ToolError,
    ToolResult,
)
from datapilot_verify.evidence import SnapshotStore, sha256_file
from datapilot_verify.rag import HybridRetriever
from datapilot_verify.semantic import SemanticRepository
from datapilot_verify.tools.base import Tool, ToolContext, tool


class SnapshotArgs(BaseModel):
    snapshot_id: str = Field(min_length=3, max_length=100)


class ChartArgs(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    dimension: str = Field(min_length=1, max_length=64)
    value_field: str = "change_amount"
    title: str = "分析结果"


def _store(context: ToolContext) -> SnapshotStore:
    return SnapshotStore(context.output_dir / "snapshots")


def _load_snapshot(
    context: ToolContext, snapshot_id: str, trace_id: str
) -> tuple[Any, ToolResult | None]:
    # 快照缺失/ID 非法返回精确错误码，而不是被工具边界统一成 INTERNAL。
    try:
        return _store(context).load(snapshot_id), None
    except ValueError:
        return None, ToolResult(
            ok=False,
            error=ToolError(
                code=ErrorCode.BAD_PARAMS, message=f"invalid snapshot id: {snapshot_id}"
            ),
            trace_id=trace_id,
        )
    except FileNotFoundError:
        return None, ToolResult(
            ok=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND, message=f"snapshot not found: {snapshot_id}"
            ),
            trace_id=trace_id,
        )


def build_artifact_tools(
    semantic_path: Path, knowledge_dir: Path
) -> tuple[Tool, Tool, Tool, Tool]:
    @tool(
        name="get_evidence",
        description=(
            "Load an auditable snapshot and return its plan, versions, SQL and "
            "verification evidence."
        ),
        args_model=SnapshotArgs,
        stage="evidence",
    )
    def get_evidence(*, args: SnapshotArgs, context: ToolContext, trace_id: str) -> ToolResult:
        snapshot, failure = _load_snapshot(context, args.snapshot_id, trace_id)
        if failure is not None:
            return failure
        return ToolResult(
            ok=True,
            data={"snapshot": snapshot.model_dump(mode="json")},
            evidence=[
                EvidenceRef(
                    evidence_id=f"snapshot:{snapshot.snapshot_id}",
                    kind="result",
                    label="Analysis snapshot",
                    source=str(_store(context).root),
                    version=snapshot.result_hash,
                )
            ],
            trace_id=trace_id,
        )

    @tool(
        name="replay_analysis",
        description=(
            "Replay a saved analysis plan against the current authorized workspace "
            "and report hash changes."
        ),
        args_model=SnapshotArgs,
        stage="evidence",
    )
    def replay_analysis(*, args: SnapshotArgs, context: ToolContext, trace_id: str) -> ToolResult:
        snapshot, failure = _load_snapshot(context, args.snapshot_id, trace_id)
        if failure is not None:
            return failure
        if snapshot.table_plan is not None:
            plan = snapshot.table_plan
            try:
                data, source_hash, result_hash = execute_table_plan(context.workspace, plan)
            except (ValueError, OSError) as exc:
                code = ErrorCode.NOT_FOUND if isinstance(exc, FileNotFoundError) else (
                    ErrorCode.EXECUTION_FAILED
                )
                return ToolResult(
                    ok=False, error=ToolError(code=code, message=f"通用表格重放失败：{exc}"),
                    trace_id=trace_id,
                )
            changes = {
                "data": {plan.dataset_id: source_hash} != snapshot.dataset_hashes,
                "result": result_hash != snapshot.result_hash,
            }
            return ToolResult(
                ok=True,
                data={
                    "snapshot_id": snapshot.snapshot_id,
                    "identical": not any(changes.values()),
                    "changes": changes,
                    "result": data,
                },
                trace_id=trace_id,
            )
        if snapshot.plan is None:
            raise ValueError("snapshot has no replayable analysis plan")
        from datapilot_verify.tools.analysis import build_run_analysis_tool
        from datapilot_verify.tools.base import ToolRegistry

        registry = ToolRegistry()
        registry.register(build_run_analysis_tool(semantic_path))
        result = registry.execute(
            "run_analysis", {"plan": snapshot.plan.model_dump(mode="json")}, context
        )
        current_hash = result.data.get("result_hash")
        semantic = SemanticRepository(semantic_path)
        metric = semantic.get(snapshot.plan.metric)
        current_dataset_hashes = {
            name: sha256_file(context.workspace / f"{name}.csv")
            for name in snapshot.dataset_hashes
            if (context.workspace / f"{name}.csv").is_file()
        }
        changes = {
            "data": current_dataset_hashes != snapshot.dataset_hashes,
            "semantic": (
                metric is None
                or metric.version != snapshot.semantic_version
                or (
                    snapshot.semantic_hash is not None
                    and semantic.content_hash != snapshot.semantic_hash
                )
            ),
            "knowledge": HybridRetriever(knowledge_dir).version != snapshot.knowledge_version,
            "result": current_hash != snapshot.result_hash,
        }
        return ToolResult(
            ok=result.ok,
            data={
                "snapshot_id": snapshot.snapshot_id,
                "original_result_hash": snapshot.result_hash,
                "replayed_result_hash": current_hash,
                "identical": result.ok and not any(changes.values()),
                "changes": changes,
                "current_dataset_hashes": current_dataset_hashes,
                "current_semantic_version": metric.version if metric else None,
                "result": result.data,
            },
            evidence=result.evidence,
            warnings=result.warnings,
            error=result.error,
            trace_id=trace_id,
        )

    @tool(
        name="make_chart",
        description="Create a portable JSON chart artifact from verified result rows.",
        args_model=ChartArgs,
        stage="presentation",
    )
    def make_chart(*, args: ChartArgs, context: ToolContext, trace_id: str) -> ToolResult:
        payload = {
            "type": "bar",
            "title": args.title,
            "x": [row.get(args.dimension) for row in args.rows],
            "y": [row.get(args.value_field) for row in args.rows],
            "value_field": args.value_field,
        }
        path = (context.output_dir / "charts" / f"chart_{trace_id}.json").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return ToolResult(
            ok=True,
            data={"chart": payload},
            artifacts=[
                ArtifactRef(
                    artifact_id=trace_id,
                    kind="chart",
                    path=path,
                    media_type="application/json",
                    sha256=digest,
                )
            ],
            evidence=[
                EvidenceRef(
                    evidence_id=f"chart:{trace_id}",
                    kind="chart",
                    label=args.title,
                    source=str(path),
                    version=digest,
                )
            ],
            trace_id=trace_id,
        )

    @tool(
        name="export_report",
        description=(
            "Export a snapshot as a self-contained Markdown audit report in the "
            "session output directory."
        ),
        args_model=SnapshotArgs,
        stage="presentation",
    )
    def export_report(*, args: SnapshotArgs, context: ToolContext, trace_id: str) -> ToolResult:
        snapshot, failure = _load_snapshot(context, args.snapshot_id, trace_id)
        if failure is not None:
            return failure
        payload = snapshot.model_dump(mode="json")
        path = (context.output_dir / "reports" / f"report_{snapshot.snapshot_id}.md").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "# DataPilot Verify 审计报告\n\n"
        text += (
            f"- 问题：{snapshot.question}\n- 快照：{snapshot.snapshot_id}\n"
            f"- 结果哈希：{snapshot.result_hash}\n\n"
        )
        text += (
            "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n```\n"
        )
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return ToolResult(
            ok=True,
            data={"snapshot_id": snapshot.snapshot_id},
            artifacts=[
                ArtifactRef(
                    artifact_id=trace_id,
                    kind="report",
                    path=path,
                    media_type="text/markdown",
                    sha256=digest,
                )
            ],
            evidence=[
                EvidenceRef(
                    evidence_id=f"report:{trace_id}",
                    kind="result",
                    label="Audit report",
                    source=str(path),
                    version=digest,
                )
            ],
            trace_id=trace_id,
        )

    return get_evidence, replay_analysis, make_chart, export_report
