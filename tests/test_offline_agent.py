from pathlib import Path

import pandas as pd

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


def test_ratio_metric_answer_reports_overall_rate_not_row_sum() -> None:
    response = OfflineAgent(ROOT).ask("按渠道比较 6 月和 7 月的退款率变化")
    assert response.status == "completed"

    frame = pd.read_csv(ROOT / "data" / "sample" / "orders.csv")
    july = frame[
        (frame["paid_at"] >= "2026-07-01") & (frame["paid_at"] <= "2026-07-31")
    ]
    expected = (july["refund_amount"] > 0).sum() / july["order_id"].nunique()
    assert f"7 月退款率为 {expected:.1%}" in response.answer


