from datetime import date

import pytest
from pydantic import ValidationError

from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, ToolResult


def test_failed_tool_result_requires_error() -> None:
    with pytest.raises(ValidationError):
        ToolResult(ok=False, trace_id="tool_test")


def test_contribution_requires_comparison() -> None:
    with pytest.raises(ValidationError, match="requires a comparison"):
        AnalysisPlan(
            plan_id="plan_1",
            dataset_ids=["orders"],
            metric="net_sales",
            dimensions=["region"],
            analysis="contribution",
            question="why did sales decline",
        )


def test_comparison_periods_cannot_overlap() -> None:
    with pytest.raises(ValidationError, match="must not overlap"):
        ComparisonSpec(
            type="custom",
            current_period=(date(2026, 7, 1), date(2026, 7, 31)),
            previous_period=(date(2026, 7, 15), date(2026, 8, 15)),
        )

