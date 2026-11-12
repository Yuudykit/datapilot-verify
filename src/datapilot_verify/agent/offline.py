from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datapilot_verify.app import build_registry
from datapilot_verify.domain.models import AnalysisPlan, AnalysisSnapshot, ComparisonSpec, SortSpec
from datapilot_verify.evidence import SnapshotStore, sha256_file
from datapilot_verify.tools import ToolContext


@dataclass(frozen=True)
class AgentEvent:
    tool: str
    trace_id: str
    ok: bool
    label: str


@dataclass(frozen=True)
class AgentResponse:
    status: str
    answer: str
    events: list[AgentEvent] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    snapshot_id: str | None = None
    clarification: dict[str, Any] | None = None


class OfflineAgent:
    """Scripted model adapter; all tools and calculations remain real."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.registry = build_registry(self.project_root)
        self.context = ToolContext(
            session_id="offline-demo",
            workspace=self.project_root / "data" / "sample",
            output_dir=self.project_root / "artifacts" / "offline-demo",
        )
        self.context.output_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots = SnapshotStore(self.context.output_dir / "snapshots")

    def ask(self, question: str, metric_choice: str | None = None) -> AgentResponse:
        normalized = question.strip()
        if not normalized:
            return AgentResponse(status="error", answer="问题不能为空。")
        if "销售额" in normalized and "净销售额" not in normalized and metric_choice is None:
            return AgentResponse(
                status="clarification",
                answer="“销售额”存在多个口径，请先确认本次分析采用哪个指标。",
                clarification={
                    "field": "metric",
                    "options": [
                        {"value": "net_sales", "label": "净销售额（扣除退款）"},
                        {"value": "gross_sales", "label": "支付金额（不扣退款）"},
                    ],
                },
            )
        if any(term in normalized for term in ("字段", "多少行", "数据质量")):
            path = (
                "stores.csv"
                if any(term in normalized for term in ("门店", "维表"))
                else "orders.csv"
            )
            result = self.registry.execute(
                "inspect_dataset", {"path": path}, self.context, allowed={"inspect_dataset"}
            )
            row_count = result.data.get("profile", {}).get("row_count", 0)
            return AgentResponse(
                status="completed" if result.ok else "error",
                answer=f"{path} 共 {row_count:,} 行。",
                events=[AgentEvent("inspect_dataset", result.trace_id, result.ok, "检查数据")],
                data=result.data,
                citations=[item.model_dump(mode="json") for item in result.evidence],
            )
        analysis_intent = any(
            term in normalized for term in ("下降", "上涨", "变化", "比较", "为什么")
        )
        definition_terms = ("定义", "口径", "包含退款", "扣除退款")
        if any(term in normalized for term in definition_terms) and not analysis_intent:
            metric = self.registry.execute("resolve_metric", {"query": normalized}, self.context)
            docs = self.registry.execute(
                "search_metric_docs", {"query": normalized, "top_k": 3}, self.context
            )
            matches = metric.data.get("matches", [])
            description = (
                matches[0]["metric"]["description"] if matches else "没有找到正式指标定义。"
            )
            return AgentResponse(
                status="completed",
                answer=description,
                events=[
                    AgentEvent("resolve_metric", metric.trace_id, metric.ok, "解析指标"),
                    AgentEvent("search_metric_docs", docs.trace_id, docs.ok, "检索口径文档"),
                ],
                data={
                    "metric": matches[0] if matches else None,
                    "documents": docs.data.get("results", []),
                },
                citations=[item.model_dump(mode="json") for item in docs.evidence],
            )
        return self._run_decline_analysis(normalized, metric_choice or "net_sales")

    def _run_decline_analysis(self, question: str, metric_id: str) -> AgentResponse:
        from datapilot_verify.agent.periods import (
            latest_paid_date,
            month_label,
            resolve_comparison_periods,
            to_comparison_dates,
        )

        metric_id = self._infer_metric(question, metric_id)
        dimension = self._infer_dimension(question)
        metric = self.registry.execute("resolve_metric", {"query": metric_id}, self.context)
        docs = self.registry.execute(
            "search_metric_docs", {"query": "净销售额扣除退款及历史口径", "top_k": 3}, self.context
        )
        data_end = latest_paid_date(self.context.workspace / "orders.csv")
        periods = resolve_comparison_periods(question, data_end) or ((2026, 7), (2026, 6))
        (cur_year, cur_month), (prev_year, prev_month) = periods
        current_period, previous_period = to_comparison_dates(periods)
        cur_label = month_label(cur_year, cur_month)
        prev_label = month_label(prev_year, prev_month)
        plan = AnalysisPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            dataset_ids=["orders", "stores"],
            metric=metric_id,
            dimensions=[dimension],
            comparison=ComparisonSpec(
                type="mom",
                current_period=current_period,
                previous_period=previous_period,
            ),
            analysis="contribution",
            sort=[SortSpec(field="change_amount", direction="asc")],
            question=question,
        )
        analysis = self.registry.execute(
            "run_analysis", {"plan": plan.model_dump(mode="json")}, self.context
        )
        events = [
            AgentEvent("resolve_metric", metric.trace_id, metric.ok, "解析指标"),
            AgentEvent("search_metric_docs", docs.trace_id, docs.ok, "检索业务文档"),
            AgentEvent("run_analysis", analysis.trace_id, analysis.ok, "执行并验证分析"),
        ]
        if not analysis.ok:
            return AgentResponse(
                status="error",
                answer=analysis.error.message if analysis.error else "分析执行失败。",
                events=events,
            )
        rows = analysis.data.get("rows", [])
        metric_info = analysis.data.get("metric", {})
        name = metric_info.get("name", metric_id)
        unit = metric_info.get("unit", "")
        # 比率类指标（退款率/客单价）的整体值不等于分组值之和，必须用
        # run_analysis 内部按相同口径聚合出的 overall 行，而不是汇总 rows。
        overall = analysis.data.get("overall") or {}
        current = float(overall.get("current_value", 0) or 0)
        previous = float(overall.get("previous_value", 0) or 0)
        change = float(overall.get("change_amount", 0) or 0)
        label = self._dimension_label(dimension)

        def row_change(row: dict[str, Any]) -> float:
            return abs(float(row.get("change_amount", 0) or 0))

        top = max(rows, key=row_change) if rows else None
        top_change = float(top.get("change_amount", 0) or 0) if top else 0.0
        top_rate = float(top.get("decline_contribution_rate", 0) or 0) if top else 0.0
        top_value = (top.get(dimension) or "未知分组") if top else ""
        if unit == "ratio":
            answer = f"{cur_label}{name}为 {current:.1%}，较 {prev_label}变化 {change:+.1%}。"
            if top is None:
                answer += "当前期间没有分组数据。"
            elif top_change < 0:
                answer += (
                    f"按{label}拆分，{top_value}变化最大（{top_change:+.1%}），"
                    f"占下降分组合计变化的 {top_rate:.1%}。"
                )
            else:
                answer += (
                    f"按{label}拆分，各分组未见下降，{top_value}变化最大（{top_change:+.1%}）。"
                )
        elif top is not None and top_change < 0:
            answer = (
                f"{cur_label}{name}为 {current:,.2f}，较 {prev_label}变化 {change:,.2f}。"
                f"{top_value}是变化最大的{label}，贡献了全部下降项的 {top_rate:.1%}，"
                "是最主要的可观察贡献因素。"
            )
        else:
            answer = (
                f"{cur_label}{name}为 {current:,.2f}，较 {prev_label}变化 {change:,.2f}"
                f"（{prev_label}为 {previous:,.2f}），未见下降分组。"
            )
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        snapshot = AnalysisSnapshot(
            snapshot_id=snapshot_id,
            created_at=datetime.now(UTC),
            question=question,
            dataset_hashes={
                "orders": sha256_file(self.context.workspace / "orders.csv"),
                "stores": sha256_file(self.context.workspace / "stores.csv"),
            },
            semantic_version=analysis.data.get("metric", {}).get("version", "unknown"),
            semantic_hash=analysis.data.get("semantic_hash"),
            knowledge_version=docs.data.get("knowledge_version", "unknown"),
            plan=plan,
            tool_trace_ids=[metric.trace_id, docs.trace_id, analysis.trace_id],
            result_hash=analysis.data.get("result_hash"),
            verification=analysis.data.get("verification", {}),
            replay_level="strong",
        )
        self.snapshots.save(snapshot)
        citations = [item.model_dump(mode="json") for item in docs.evidence + analysis.evidence]
        return AgentResponse(
            status="completed",
            answer=answer,
            events=events,
            data={
                "plan": plan.model_dump(mode="json"),
                "rows": rows,
                "verification": analysis.data.get("verification"),
            },
            citations=citations,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def _infer_metric(question: str, fallback: str) -> str:
        if "退款率" in question or "退货率" in question:
            return "refund_rate"
        if "客单价" in question or "平均订单" in question:
            return "avg_order_value"
        known = {"net_sales", "refund_rate", "avg_order_value"}
        return fallback if fallback in known else "net_sales"

    @staticmethod
    def _infer_dimension(question: str) -> str:
        for term, dimension in (
            (("渠道",), "channel"), (("品类", "类别"), "category"),
            (("城市",), "city"), (("门店",), "store_id"),
        ):
            if any(item in question for item in term):
                return dimension
        return "region"

    @staticmethod
    def _dimension_label(dimension: str) -> str:
        labels = {
            "region": "区域",
            "city": "城市",
            "store_id": "门店",
            "category": "品类",
            "channel": "渠道",
        }
        return labels[dimension]
