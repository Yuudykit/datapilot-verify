from datapilot_verify.engine import enrich_contribution
from datapilot_verify.verification import verify_comparison_rows


def test_numeric_verification_and_contribution() -> None:
    rows = [
        {"region": "华东", "current_value": 80, "previous_value": 100, "change_amount": -20, "change_rate": -0.2},
        {"region": "华南", "current_value": 95, "previous_value": 100, "change_amount": -5, "change_rate": -0.05},
        {"region": "华北", "current_value": 110, "previous_value": 100, "change_amount": 10, "change_rate": 0.1},
    ]
    report = verify_comparison_rows(rows)
    assert report.passed
    enriched = enrich_contribution(rows)
    assert enriched[0]["decline_contribution_rate"] == 0.8
    assert enriched[1]["decline_contribution_rate"] == 0.2
    assert enriched[2]["decline_contribution_rate"] == 0.0

