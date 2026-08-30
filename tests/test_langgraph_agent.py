from pathlib import Path

from datapilot_verify.agent.graph import build_graph
from datapilot_verify.app import build_registry
from datapilot_verify.tools import ToolContext

ROOT = Path(__file__).resolve().parents[1]


def test_langgraph_runs_validated_tool_chain() -> None:
    result = build_graph(ROOT).invoke("7 月净销售额为什么下降？", thread_id="graph-test")
    assert result["status"] == "completed"
    assert [item["tool"] for item in result["events"]] == [
        "resolve_metric", "search_metric_docs", "run_analysis"
    ]
    assert result["data"]["verification"]["passed"]


def test_langgraph_metric_clarification_can_resume() -> None:
    graph = build_graph(ROOT)
    initial = graph.invoke("7 月销售额为什么下降？", thread_id="clarify-test")
    assert initial["status"] == "clarification"
    assert initial["thread_id"] == "clarify-test"
    assert initial["clarification"]["field"] == "metric"
    resumed = graph.resume("clarify-test", "net_sales")
    assert resumed["status"] == "completed"


def test_langgraph_changes_plan_for_metric_and_dimension() -> None:
    result = build_graph(ROOT).invoke("按渠道看退款率变化", thread_id="dynamic-plan")
    assert result["status"] == "completed"
    assert result["data"]["plan"]["metric"] == "refund_rate"
    assert result["data"]["plan"]["dimensions"] == ["channel"]
    assert "退款率" in result["answer"]


def test_langgraph_routes_dataset_question() -> None:
    result = build_graph(ROOT).invoke("这张表有多少行？", thread_id="dataset-route")
    assert result["status"] == "completed"
    assert result["data"]["profile"]["row_count"] == 3123
    assert "order_id" in result["answer"]


def test_langgraph_uses_question_months_for_comparison() -> None:
    result = build_graph(ROOT).invoke(
        "按渠道比较 5 月和 6 月的退款率变化", thread_id="period-route"
    )
    assert result["status"] == "completed"
    comparison = result["data"]["plan"]["comparison"]
    assert comparison["current_period"][0] == "2026-06-01"
    assert comparison["previous_period"][0] == "2026-05-01"


def test_langgraph_prefers_analysis_over_definition_in_mixed_question() -> None:
    result = build_graph(ROOT).invoke(
        "净销售额的口径是什么？顺便按渠道看 7 月为什么下降", thread_id="mixed-intent"
    )
    assert result["status"] == "completed"
    tools = [item["tool"] for item in result["events"]]
    assert "run_analysis" in tools


def test_langgraph_inspects_stores_table_when_asked() -> None:
    result = build_graph(ROOT).invoke("门店维表有多少行？", thread_id="stores-route")
    assert result["status"] == "completed"
    assert result["data"]["profile"]["row_count"] == 11
    assert "store_id" in result["answer"]


def test_langgraph_rejects_unrelated_question() -> None:
    result = build_graph(ROOT).invoke("今天天气怎么样", thread_id="unsupported-route")
    assert result["status"] == "unsupported"


def test_snapshot_evidence_replay_and_report() -> None:
    graph = build_graph(ROOT)
    result = graph.invoke("7 月净销售额为什么下降？", thread_id="replay-chain")
    snapshot_id = result["snapshot_id"]
    registry = build_registry(ROOT)
    context = ToolContext(
        "test", ROOT / "data" / "sample", ROOT / "artifacts" / "langgraph"
    )
    evidence = registry.execute("get_evidence", {"snapshot_id": snapshot_id}, context)
    replay = registry.execute("replay_analysis", {"snapshot_id": snapshot_id}, context)
    report = registry.execute("export_report", {"snapshot_id": snapshot_id}, context)
    assert evidence.ok
    assert replay.ok and replay.data["identical"]
    assert replay.data["changes"] == {
        "data": False,
        "semantic": False,
        "knowledge": False,
        "result": False,
    }
    assert report.ok and report.artifacts[0].path.is_file()


def test_sqlite_checkpoint_survives_graph_rebuild() -> None:
    thread_id = "persistent-clarification"
    first = build_graph(ROOT)
    interrupted = first.invoke("7 月销售额为什么下降？", thread_id=thread_id)
    assert interrupted["status"] == "clarification"
    rebuilt = build_graph(ROOT)
    resumed = rebuilt.resume(thread_id, "net_sales")
    assert resumed["status"] == "completed"
