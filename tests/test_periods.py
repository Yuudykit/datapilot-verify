from datetime import date
from pathlib import Path

from datapilot_verify.agent.periods import (
    latest_paid_date,
    mentioned_months,
    resolve_comparison_periods,
    to_comparison_dates,
)

ROOT = Path(__file__).resolve().parents[1]


def test_mentions_two_bare_months_use_data_year() -> None:
    periods = resolve_comparison_periods("按渠道比较 5 月和 6 月", date(2026, 7, 31))
    assert periods == ((2026, 6), (2026, 5))


def test_single_mentioned_month_defaults_to_previous() -> None:
    periods = resolve_comparison_periods("7月净销售额为什么下降", date(2026, 7, 31))
    assert periods == ((2026, 7), (2026, 6))


def test_january_crosses_year_backwards() -> None:
    periods = resolve_comparison_periods("看 1 月的数据", date(2026, 1, 31))
    assert periods == ((2026, 1), (2025, 12))


def test_explicit_year_beats_data_year() -> None:
    periods = resolve_comparison_periods("比较 2025年12月 和 1 月", date(2026, 8, 20))
    assert periods == ((2026, 1), (2025, 12))


def test_no_mention_falls_back_to_latest_data_month() -> None:
    periods = resolve_comparison_periods("净销售额为什么下降", date(2026, 7, 31))
    assert periods == ((2026, 7), (2026, 6))


def test_no_mention_and_no_data_returns_none() -> None:
    assert resolve_comparison_periods("净销售额为什么下降", None) is None


def test_invalid_month_ignored() -> None:
    assert mentioned_months("第 13 月和 0 月") == []


def test_to_comparison_dates_bounds() -> None:
    current, previous = to_comparison_dates(((2026, 7), (2026, 6)))
    assert current == (date(2026, 7, 1), date(2026, 7, 31))
    assert previous == (date(2026, 6, 1), date(2026, 6, 30))


def test_latest_paid_date_reads_sample() -> None:
    assert latest_paid_date(ROOT / "data" / "sample" / "orders.csv") == date(2026, 7, 31)


def test_latest_paid_date_survives_missing_file(tmp_path: Path) -> None:
    assert latest_paid_date(tmp_path / "missing.csv") is None
