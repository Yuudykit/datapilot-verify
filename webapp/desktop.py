from __future__ import annotations

import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datapilot_verify.agent import build_graph, build_live_tool_loop
from datapilot_verify.config import get_settings
from datapilot_verify.data import DatasetCatalog
from datapilot_verify.data.tables import (
    OPERATIONS,
    execute_table_plan,
    import_table,
    list_tables,
    parse_question,
    table_metadata,
)
from datapilot_verify.domain.models import AnalysisSnapshot, TablePlan
from datapilot_verify.evidence import SnapshotStore, sha256_file
from datapilot_verify.tools import ToolContext

_SNAPSHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,100}$")


def _valid_snapshot_id(snapshot_id: str) -> bool:
    return bool(_SNAPSHOT_ID_PATTERN.match(snapshot_id))


def normalize_live_result(
    question: str, result: dict[str, Any], workspace: Path, output_dir: Path
) -> dict[str, Any]:
    """把 live 工具循环的原始输出归一化为界面/API 使用的统一结构，
    并为成功的 run_analysis 生成审计快照。桌面端与 API 共用。"""
    trace = result.get("tool_trace", [])
    successful = [item for item in trace if item.get("result", {}).get("ok")]
    analysis = next((item for item in successful if item.get("name") == "run_analysis"), None)
    events = [
        {
            "tool": item.get("name"),
            "trace_id": item.get("result", {}).get("trace_id", ""),
            "ok": item.get("result", {}).get("ok", False),
            "label": item.get("name", "tool"),
        }
        for item in trace
    ]
    normalized = {**result, "events": events, "citations": [], "data": {}}
    if analysis is None:
        failed_analysis = next(
            (item for item in reversed(trace) if item.get("name") == "run_analysis"), None
        )
        if failed_analysis is not None:
            error = failed_analysis.get("result", {}).get("error") or {}
            normalized.update(status="error", answer=error.get("message") or "分析执行失败。")
        return normalized
    payload = analysis["result"]
    data = payload.get("data", {})
    normalized["data"] = data
    normalized["citations"] = [
        evidence
        for item in successful
        for evidence in item.get("result", {}).get("evidence", [])
    ]
    plan_payload = data.get("plan")
    if not plan_payload:
        return normalized
    snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
    metric = data.get("metric", {})
    query = next(
        (item for item in payload.get("evidence", []) if item.get("kind") == "query"),
        None,
    )
    knowledge = next(
        (
            item.get("result", {}).get("data", {}).get("knowledge_version")
            for item in successful
            if item.get("name") == "search_metric_docs"
        ),
        "unknown",
    )
    snapshot = AnalysisSnapshot(
        snapshot_id=snapshot_id,
        created_at=datetime.now(UTC),
        question=question,
        dataset_hashes={
            name: sha256_file(workspace / f"{name}.csv")
            for name in ("orders", "stores")
        },
        semantic_version=metric.get("version", "unknown"),
        semantic_hash=data.get("semantic_hash"),
        knowledge_version=knowledge or "unknown",
        plan=plan_payload,
        tool_trace_ids=[item["trace_id"] for item in events if item["trace_id"]],
        sql=query.get("metadata", {}).get("sql") if query else None,
        result_hash=data.get("result_hash"),
        verification=data.get("verification", {}),
        replay_level="strong",
    )
    SnapshotStore(output_dir / "snapshots").save(snapshot)
    normalized["snapshot_id"] = snapshot_id
    return normalized


class DesktopApp:
    """Single-user application service used by the Streamlit shell."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        settings = get_settings()
        self.workspace = (self.project_root / settings.workspace_root).resolve()
        self.output = (self.project_root / settings.artifact_root / "desktop").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self._ensure_sample_workspace()
        self._graph: Any | None = None
        self._datasets_cache: tuple[tuple, list[dict[str, Any]]] | None = None

    def _mock_graph(self) -> Any:
        # 复用同一 LangGraph 实例（含 checkpointer 连接）：每次点击都重建
        # registry/检索器/checkpointer 是纯浪费（BUG-020）。
        if self._graph is None:
            graph = build_graph(self.project_root)
            graph.context = ToolContext("desktop", self.workspace, self.output)
            self._graph = graph
        return self._graph

    def _ensure_sample_workspace(self) -> None:
        for name in ("orders.csv", "stores.csv"):
            target = self.workspace / name
            if not target.is_file():
                shutil.copy2(self.project_root / "data" / "sample" / name, target)

    def datasets(self) -> list[dict[str, Any]]:
        names = sorted(self._files())
        signature = tuple(
            (name, stat.st_mtime_ns, stat.st_size)
            for name, stat in ((n, (self.workspace / n).stat()) for n in names)
        )
        if self._datasets_cache is not None and self._datasets_cache[0] == signature:
            return self._datasets_cache[1]
        catalog = DatasetCatalog(self.workspace)
        profiles = [catalog.profile(name).model_dump(mode="json") for name in names]
        self._datasets_cache = (signature, profiles)
        return profiles

    def _files(self) -> list[str]:
        return [
            path.name
            for path in self.workspace.iterdir()
            if path.is_file() and path.suffix.casefold() in DatasetCatalog.SUPPORTED_SUFFIXES
        ]

    def tables(self) -> list[dict[str, Any]]:
        return list_tables(self.workspace)

    def upload(
        self, filename: str, content: bytes, role: str = "table",
        *, sheet: str | None = None, header_row: int = 1,
    ) -> dict[str, Any]:
        if role == "table":
            return import_table(self.workspace, filename, content, sheet, header_row)

        import io

        import pandas as pd

        suffix = Path(filename).suffix.casefold()
        if suffix not in DatasetCatalog.SUPPORTED_SUFFIXES:
            raise ValueError("仅支持 CSV、XLSX、XLS 文件")
        if role not in {"orders", "stores"}:
            raise ValueError("数据角色必须是 orders 或 stores")
        frame = (
            pd.read_csv(io.BytesIO(content))
            if suffix == ".csv"
            else pd.read_excel(io.BytesIO(content))
        )
        required = {
            "orders": {
                "order_id",
                "paid_at",
                "store_id",
                "category",
                "channel",
                "paid_amount",
                "refund_amount",
            },
            "stores": {"store_id", "region", "city"},
        }[role]
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{role} 缺少字段：{', '.join(missing)}")
        target = self.workspace / f"{role}.csv"
        frame.to_csv(target, index=False, encoding="utf-8")
        return DatasetCatalog(self.workspace).profile(target.name).model_dump(mode="json")

    def analyze_table(self, question: str, table: str | TablePlan) -> dict[str, Any]:
        plan = parse_question(table, question) if isinstance(table, str) else table
        metadata = table_metadata(self.workspace, plan.dataset_id)
        data, source_hash, result_hash = execute_table_plan(self.workspace, plan)
        source = metadata["filename"]
        if metadata["sheet"]:
            source += f" / {metadata['sheet']}"
        title = OPERATIONS[plan.operation]
        if plan.operation == "profile":
            answer = (
                f"「{source}」有 {data['row_count']:,} 条非空记录、{len(data['rows'])} 个字段。"
                f"完全重复的记录有 {data['duplicate_rows']:,} 条。"
            )
        elif plan.group_by:
            answer = (
                f"「{source}」按「{plan.group_by}」统计{title}。"
                f"本次纳入 {data['row_count']:,} 条记录。"
            )
        else:
            value = data["rows"][0]["value"]
            answer = f"「{source}」{title}为 {value if value is not None else '无可用数值'}。"
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        trace_id = f"tool_{uuid.uuid4().hex[:12]}"
        SnapshotStore(self.output / "snapshots").save(AnalysisSnapshot(
            snapshot_id=snapshot_id,
            created_at=datetime.now(UTC),
            question=question,
            dataset_hashes={plan.dataset_id: source_hash},
            semantic_version="n/a",
            knowledge_version="n/a",
            table_plan=plan,
            table_source=metadata,
            tool_trace_ids=[trace_id],
            result_hash=result_hash,
            replay_level="strong",
        ))
        return {
            "status": "completed",
            "answer": answer,
            "data": {"table_result": data, "table_plan": plan.model_dump(mode="json")},
            "snapshot_id": snapshot_id,
            "events": [{"label": title, "tool": "analyze_table", "trace_id": trace_id, "ok": True}],
            "citations": [{"label": "导入表格", "source": source, "version": source_hash}],
        }

    def analyze(self, question: str, metric_choice: str | None = None) -> dict[str, Any]:
        settings = get_settings()
        if settings.llm_mode == "live":
            if not settings.llm_api_key:
                raise ValueError(
                    "DATAPILOT_LLM_MODE=live 但缺少 DATAPILOT_LLM_API_KEY；"
                    "请在项目根目录的 .env 配置 Key 后重启，或改用 mock 模式。"
                )
            loop = build_live_tool_loop(
                self.project_root,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                max_steps=settings.max_tool_steps,
                workspace=self.workspace,
                output_dir=self.output,
            )
            return self._normalize_live(question, loop.run(question))
        graph = self._mock_graph()
        return graph.invoke(question, metric_choice=metric_choice)

    def resume(self, thread_id: str, value: str) -> dict[str, Any]:
        """按澄清线程继续执行（mock 模式的口径确认走这条链路）。"""
        return self._mock_graph().resume(thread_id, value)

    def _normalize_live(self, question: str, result: dict[str, Any]) -> dict[str, Any]:
        return normalize_live_result(question, result, self.workspace, self.output)

    def replay(self, snapshot_id: str) -> dict[str, Any]:
        from datapilot_verify.app import build_registry

        return build_registry(self.project_root).execute(
            "replay_analysis", {"snapshot_id": snapshot_id}, self.context()
        ).model_dump(mode="json")

    def report(self, snapshot_id: str) -> Path:
        # 快照 ID 只会指向一次性导出的报告，已存在时直接复用，避免每次
        # 页面重渲染都重新导出（BUG-020）。
        if _valid_snapshot_id(snapshot_id):
            cached = self.output / "reports" / f"report_{snapshot_id}.md"
            if cached.is_file():
                return cached
        from datapilot_verify.app import build_registry

        result = build_registry(self.project_root).execute(
            "export_report", {"snapshot_id": snapshot_id}, self.context()
        )
        if not result.ok or not result.artifacts:
            raise RuntimeError(result.error.message if result.error else "报告导出失败")
        return result.artifacts[0].path

    def context(self) -> ToolContext:
        return ToolContext("desktop", self.workspace, self.output)
