from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datapilot_verify.agent import build_graph, build_live_tool_loop
from datapilot_verify.config import get_settings
from datapilot_verify.data import DatasetCatalog
from datapilot_verify.domain.models import AnalysisSnapshot
from datapilot_verify.evidence import SnapshotStore, sha256_file
from datapilot_verify.tools import ToolContext


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

    def _ensure_sample_workspace(self) -> None:
        for name in ("orders.csv", "stores.csv"):
            target = self.workspace / name
            if not target.is_file():
                shutil.copy2(self.project_root / "data" / "sample" / name, target)

    def datasets(self) -> list[dict[str, Any]]:
        catalog = DatasetCatalog(self.workspace)
        return [catalog.profile(path).model_dump(mode="json") for path in sorted(self._files())]

    def _files(self) -> list[str]:
        return [
            path.name
            for path in self.workspace.iterdir()
            if path.is_file() and path.suffix.casefold() in DatasetCatalog.SUPPORTED_SUFFIXES
        ]

    def upload(self, filename: str, content: bytes, role: str) -> dict[str, Any]:
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

    def analyze(self, question: str, metric_choice: str | None = None) -> dict[str, Any]:
        settings = get_settings()
        if settings.llm_mode == "live" and settings.llm_api_key:
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
        graph = build_graph(self.project_root)
        graph.context = ToolContext("desktop", self.workspace, self.output)
        return graph.invoke(question, metric_choice=metric_choice)

    def _normalize_live(self, question: str, result: dict[str, Any]) -> dict[str, Any]:
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
                name: sha256_file(self.workspace / f"{name}.csv")
                for name in ("orders", "stores")
            },
            semantic_version=metric.get("version", "unknown"),
            knowledge_version=knowledge or "unknown",
            plan=plan_payload,
            tool_trace_ids=[item["trace_id"] for item in events if item["trace_id"]],
            sql=query.get("metadata", {}).get("sql") if query else None,
            result_hash=data.get("result_hash"),
            verification=data.get("verification", {}),
            replay_level="strong",
        )
        SnapshotStore(self.output / "snapshots").save(snapshot)
        normalized["snapshot_id"] = snapshot_id
        return normalized

    def replay(self, snapshot_id: str) -> dict[str, Any]:
        from datapilot_verify.app import build_registry

        return build_registry(self.project_root).execute(
            "replay_analysis", {"snapshot_id": snapshot_id}, self.context()
        ).model_dump(mode="json")

    def report(self, snapshot_id: str) -> Path:
        from datapilot_verify.app import build_registry

        result = build_registry(self.project_root).execute(
            "export_report", {"snapshot_id": snapshot_id}, self.context()
        )
        if not result.ok or not result.artifacts:
            raise RuntimeError(result.error.message if result.error else "报告导出失败")
        return result.artifacts[0].path

    def context(self) -> ToolContext:
        return ToolContext("desktop", self.workspace, self.output)
