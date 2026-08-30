from pathlib import Path

from datapilot_verify.semantic import SemanticRepository

ROOT = Path(__file__).resolve().parents[1]


def test_resolves_alias_to_authoritative_metric() -> None:
    repository = SemanticRepository(ROOT / "data" / "semantic" / "metrics.yml")
    matches = repository.resolve("请分析净GMV环比")
    assert matches[0].metric.metric_id == "net_sales"
    assert matches[0].metric.expression == "sum(paid_amount - refund_amount)"


def test_unknown_metric_has_no_high_confidence_match() -> None:
    repository = SemanticRepository(ROOT / "data" / "semantic" / "metrics.yml")
    matches = repository.resolve("天气温度")
    assert not matches or matches[0].score < 0.8

