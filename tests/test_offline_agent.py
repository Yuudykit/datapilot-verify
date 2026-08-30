from pathlib import Path

from datapilot_verify.agent import OfflineAgent


ROOT = Path(__file__).resolve().parents[1]


def test_asks_for_ambiguous_metric() -> None:
    response = OfflineAgent(ROOT).ask("7 月销售额为什么下降？")
    assert response.status == "clarification"
    assert response.clarification is not None


def test_runs_real_tools_after_metric_is_clear() -> None:
    response = OfflineAgent(ROOT).ask("7 月净销售额为什么下降？")
    assert response.status == "completed"
    assert [event.tool for event in response.events] == [
        "resolve_metric",
        "search_metric_docs",
        "run_analysis",
    ]
    assert response.data["verification"]["passed"]
    assert response.snapshot_id is not None
    assert "华东" in response.answer

