from pathlib import Path

import pytest

from datapilot_verify.data import DatasetCatalog

ROOT = Path(__file__).resolve().parents[1]


def test_profiles_sample_orders() -> None:
    catalog = DatasetCatalog(ROOT / "data" / "sample")
    profile = catalog.profile("orders.csv")
    assert profile.row_count == 3123
    assert profile.time_range is not None
    assert profile.time_range[0].isoformat() == "2026-06-01"
    assert {column.name for column in profile.columns} >= {"order_id", "paid_amount"}


def test_rejects_path_escape() -> None:
    catalog = DatasetCatalog(ROOT / "data" / "sample")
    with pytest.raises(ValueError, match="escapes"):
        catalog.profile("../semantic/metrics.yml")

