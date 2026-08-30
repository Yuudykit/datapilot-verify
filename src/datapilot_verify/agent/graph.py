from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from datapilot_verify.app import build_registry
from datapilot_verify.domain.models import AnalysisSnapshot
from datapilot_verify.evidence import SnapshotStore, sha256_file
from datapilot_verify.tools import ToolContext, ToolRegistry


class AgentState(TypedDict, total=False):
    question: str
    metric_choice: str | None
    status: str
    answer: str
    events: list[dict[str, Any]]
    data: dict[str, Any]
    citations: list[dict[str, Any]]
    clarification: dict[str, Any] | None
    error: str | None
    snapshot_id: str | None


def _event(name: str, result: Any, label: str) -> dict[str, Any]:
    return {"tool": name, "trace_id": result.trace_id, "ok": result.ok, "label": label}


class DataPilotGraph:
    """LangGraph execution layer backed by the existing validated ToolRegistry.

    The graph is deterministic by default; a model can be added later at the
    routing boundary without changing tool contracts or audit state.
    """

    def __init__(self, project_root: Path, checkpointer: Any | None = None) -> None:
        self.project_root = project_root.resolve()
        self.registry: ToolRegistry = build_registry(self.project_root)
        self.context = ToolContext(
            session_id="langgraph",
            workspace=self.project_root / "data" / "sample",
            output_dir=self.project_root / "artifacts" / "langgraph",
        )
        self.context.output_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = None
        if checkpointer is None:
            checkpoint_path = self.context.output_dir / "checkpoints.sqlite"
            self._checkpoint_connection = sqlite3.connect(
                checkpoint_path, check_same_thread=False
            )
            checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer = checkpointer
        self.graph = self._build()

    def _build(self):
        builder = StateGraph(AgentState)
        builder.add_node("resolve_metric", self._resolve_metric)
        builder.add_node("clarify_metric", self._clarify_metric)
        builder.add_node("inspect_dataset", self._inspect_dataset)
        builder.add_node("answer_metric", self._answer_metric)
        builder.add_node("unsupported", self._unsupported)
        builder.add_node("search_docs", self._search_docs)
        builder.add_node("run_analysis", self._run_analysis)
        builder.add_edge(START, "resolve_metric")
        builder.add_conditional_edges(
            "resolve_metric", self._route_after_metric,
            {
                "clarify_metric": "clarify_metric",
                "inspect_dataset": "inspect_dataset",
                "answer_metric": "answer_metric",
                "unsupported": "unsupported",
                "search_docs": "search_docs",
            },
        )
        builder.add_conditional_edges(
            "clarify_metric", self._route_after_clarify,
            {"resolve_metric": "resolve_metric", "search_docs": "search_docs", END: END},
        )
        builder.add_edge("search_docs", "run_analysis")
        builder.add_edge("inspect_dataset", END)
        builder.add_edge("answer_metric", END)
        builder.add_edge("unsupported", END)
        builder.add_edge("run_analysis", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _resolve_metric(self, state: AgentState) -> dict[str, Any]:
        query = state.get("metric_choice") or state["question"]
        result = self.registry.execute("resolve_metric", {"query": query}, self.context)
        events = [*state.get("events", []), _event("resolve_metric", result, "解析指标")]
        matches = result.data.get("matches", [])
        return {"data": {**state.get("data", {}), "metric_matches": matches}, "events": events}

    def _route_after_metric(self, state: AgentState) -> str:
        question = state["question"]
        if any(term in question for term in ("字段", "多少行", "数据质量")):
            return "inspect_dataset"
        matches = state.get("data", {}).get("metric_matches", [])
        ambiguous = (
            not state.get("metric_choice")
            and "销售额" in state["question"]
            and "净销售额" not in state["question"]
        )
        if ambiguous:
            return "clarify_metric"
        # 分析类意图优先于口径问答：混合问题（"口径是什么？顺便看为什么下降"）
        # 应当进入完整分析链路，而不是只返回定义文本。
        analysis_intent = any(
            term in question for term in ("下降", "上涨", "变化", "比较", "为什么")
        )
        if analysis_intent:
            return "search_docs" if matches else "unsupported"
        if any(term in question for term in ("定义", "口径", "包含退款", "扣除退款")):
            return "answer_metric"
        return "search_docs" if matches else "unsupported"

    def _inspect_dataset(self, state: AgentState) -> dict[str, Any]:
        path = (
            "stores.csv"
            if any(term in state["question"] for term in ("门店", "维表"))
            else "orders.csv"
        )
        result = self.registry.execute(
            "inspect_dataset", {"path": path}, self.context, allowed={"inspect_dataset"}
        )
        profile = result.data.get("profile", {})
        columns = [item.get("name", "") for item in profile.get("columns", [])]
        column_text = "、".join(columns)
        return {
            "status": "completed" if result.ok else "error",
            "answer": (
                f"{profile.get('filename', path)} 共 {profile.get('row_count', 0):,} 行，"
                f"字段包括：{column_text}。"
            ),
            "events": [*state.get("events", []), _event("inspect_dataset", result, "检查数据")],
            "data": {**state.get("data", {}), **result.data},
            "citations": [x.model_dump(mode="json") for x in result.evidence],
        }

    def _answer_metric(self, state: AgentState) -> dict[str, Any]:
        matches = state.get("data", {}).get("metric_matches", [])
        metric = matches[0]["metric"] if matches else None
        docs = self.registry.execute(
            "search_metric_docs", {"query": state["question"], "top_k": 3}, self.context
        )
        return {
            "status": "completed" if metric else "error",
            "answer": metric["description"] if metric else "没有找到正式指标定义。",
            "data": state.get("data", {}),
            "events": [
                *state.get("events", []),
                _event("search_metric_docs", docs, "检索口径文档"),
            ],
            "citations": [x.model_dump(mode="json") for x in docs.evidence],
        }

    @staticmethod
    def _unsupported(state: AgentState) -> dict[str, Any]:
        return {
            "status": "unsupported",
            "answer": "当前只能回答已注册数据集中的经营指标、口径和数据质量问题。",
            "events": state.get("events", []),
            "data": state.get("data", {}),
            "citations": [],
        }

    def _clarify_metric(self, state: AgentState) -> dict[str, Any]:
        payload = {
            "field": "metric",
            "options": [
                {"value": "net_sales", "label": "净销售额（扣除退款）"},
                {"value": "gross_sales", "label": "支付金额（不扣退款）"},
            ],
        }
        # An interrupt makes the choice resumable with Command(resume=...).
        answer = interrupt(payload)
        choice = answer if isinstance(answer, str) else None
        if choice:
            return {"metric_choice": choice, "clarification": None}
        return {
            "status": "clarification",
            "clarification": payload,
            "answer": "请先确认分析指标口径。",
        }

    def _route_after_clarify(self, state: AgentState) -> str:
        return "resolve_metric" if state.get("metric_choice") else END

    def _search_docs(self, state: AgentState) -> dict[str, Any]:
        result = self.registry.execute(
            "search_metric_docs", {"query": "净销售额扣除退款及历史口径", "top_k": 3}, self.context
        )
        return {
            "events": [
                *state.get("events", []),
                _event("search_metric_docs", result, "检索业务文档"),
            ],
            "data": {
                **state.get("data", {}),
                "documents": result.data.get("results", []),
                "knowledge_version": result.data.get("knowledge_version", "unknown"),
            },
            "citations": [x.model_dump(mode="json") for x in result.evidence],
        }

    def _run_analysis(self, state: AgentState) -> dict[str, Any]:

        from datapilot_verify.agent.periods import (
            latest_paid_date,
            month_label,
            resolve_comparison_periods,
            to_comparison_dates,
        )
        from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, SortSpec

        question = state["question"]
        metric_id = self._metric_id(state)
        dimension = self._dimension(question)
        # 对比期间不再硬编码：优先取问题里提到的月份，否则用数据最新月份
        # （BUG-017）。样例兜底仅在无数据且无月份提示时使用。
        data_end = latest_paid_date(self.context.workspace / "orders.csv")
        periods = resolve_comparison_periods(question, data_end) or (
            ((2026, 7), (2026, 6))
        )
        (cur_year, cur_month), (prev_year, prev_month) = periods
        current_period, previous_period = to_comparison_dates(periods)
        cur_label = month_label(cur_year, cur_month)
        prev_label = month_label(prev_year, prev_month)
        plan = AnalysisPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            dataset_ids=["orders", "stores"], metric=metric_id, dimensions=[dimension],
            comparison=ComparisonSpec(
                type="mom", current_period=current_period, previous_period=previous_period,
            ), analysis="contribution", sort=[SortSpec(field="change_amount", direction="asc")],
            question=state["question"],
        )
        result = self.registry.execute(
            "run_analysis", {"plan": plan.model_dump(mode="json")}, self.context
        )
        rows = result.data.get("rows", [])
        top = max(rows, key=lambda row: abs(row.get("change_amount", 0))) if rows else {}
        metric = result.data.get("metric", {})
        name = metric.get("name", metric_id)
        unit = metric.get("unit", "")
        overall = result.data.get("overall") or {}
        top_value = top.get(dimension) or "未知分组"
        if unit == "ratio":
            answer = (
                f"整体{name}从 {prev_label} {overall.get('previous_value', 0):.1%}变为 "
                f"{cur_label} {overall.get('current_value', 0):.1%}。按"
                f"{self._dimension_label(dimension)}拆分，{top_value}"
                f"变化最大（{top.get('change_amount', 0):+.1%}）。"
            )
        else:
            total_current = overall.get("current_value", 0)
            total_change = overall.get("change_amount", 0)
            answer = (
                f"{cur_label}{name}为 {total_current:,.2f}，"
                f"较 {prev_label}变化 {total_change:,.2f}。"
                f"{top_value}是变化最大的"
                f"{self._dimension_label(dimension)}。"
            )
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        query_evidence = next((item for item in result.evidence if item.kind == "query"), None)
        snapshot = AnalysisSnapshot(
            snapshot_id=snapshot_id,
            created_at=datetime.now(UTC),
            question=question,
            dataset_hashes={
                "orders": sha256_file(self.context.workspace / "orders.csv"),
                "stores": sha256_file(self.context.workspace / "stores.csv"),
            },
            semantic_version=metric.get("version", "unknown"),
            knowledge_version=state.get("data", {}).get("knowledge_version", "unknown"),
            plan=plan,
            tool_trace_ids=[item["trace_id"] for item in state.get("events", [])]
            + [result.trace_id],
            sql=query_evidence.metadata.get("sql") if query_evidence else None,
            result_hash=result.data.get("result_hash"),
            verification=result.data.get("verification", {}),
            replay_level="strong",
        )
        SnapshotStore(self.context.output_dir / "snapshots").save(snapshot)
        return {
            "status": "completed" if result.ok else "error",
            "answer": answer,
            "events": [*state.get("events", []), _event("run_analysis", result, "执行并验证分析")],
            "data": {**state.get("data", {}), "plan": plan.model_dump(mode="json"), **result.data},
            "citations": [
                *state.get("citations", []),
                *[x.model_dump(mode="json") for x in result.evidence],
            ],
            "snapshot_id": snapshot_id,
        }

    def invoke(
        self,
        question: str,
        *,
        metric_choice: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        if not question.strip():
            return {"status": "error", "answer": "问题不能为空。", "events": []}
        config = {"configurable": {"thread_id": thread_id or f"thread_{uuid.uuid4().hex[:10]}"}}
        result = self.graph.invoke(
            {"question": question, "metric_choice": metric_choice, "events": []}, config
        )
        return self._public_result(result, config["configurable"]["thread_id"])

    def resume(self, thread_id: str, value: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        return self._public_result(self.graph.invoke(Command(resume=value), config), thread_id)

    @staticmethod
    def _metric_id(state: AgentState) -> str:
        choice = state.get("metric_choice")
        if choice in {"net_sales", "refund_rate", "avg_order_value"}:
            return choice
        matches = state.get("data", {}).get("metric_matches", [])
        return matches[0]["metric"]["metric_id"] if matches else "net_sales"

    @staticmethod
    def _dimension(question: str) -> str:
        for terms, dimension in (
            (("渠道",), "channel"), (("品类", "类别"), "category"),
            (("城市",), "city"), (("门店",), "store_id"),
        ):
            if any(term in question for term in terms):
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

    @staticmethod
    def _public_result(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
        interrupts = result.pop("__interrupt__", [])
        result["thread_id"] = thread_id
        if interrupts:
            result.update(
                status="clarification",
                answer="请先确认分析指标口径。",
                clarification=interrupts[0].value,
            )
        return result


def build_graph(project_root: Path, checkpointer: Any | None = None) -> DataPilotGraph:
    return DataPilotGraph(project_root, checkpointer)
