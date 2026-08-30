from datetime import date
from pathlib import Path

from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, SortSpec
from datapilot_verify.tools import ToolContext, ToolRegistry
from datapilot_verify.tools.analysis import build_run_analysis_tool

ROOT = Path(__file__).resolve().parents[1]


def test_run_analysis_returns_verified_evidence() -> None:
    registry = ToolRegistry()
    registry.register(build_run_analysis_tool(ROOT / "data" / "semantic" / "metrics.yml"))
    plan = AnalysisPlan(
        plan_id="test_tool",
        dataset_ids=["orders", "stores"],
        metric="net_sales",
        dimensions=["region"],
        comparison=ComparisonSpec(
            type="mom",
            current_period=(date(2026, 7, 1), date(2026, 7, 31)),
            previous_period=(date(2026, 6, 1), date(2026, 6, 30)),
        ),
        analysis="contribution",
        sort=[SortSpec(field="change_amount", direction="asc")],
        question="why",
    )
    result = registry.execute(
        "run_analysis",
        {"plan": plan.model_dump(mode="json")},
        ToolContext("test", ROOT / "data" / "sample", ROOT / "artifacts" / "test"),
    )
    assert result.ok
    assert result.data["verification"]["passed"]
    assert result.data["rows"][0]["region"] == "华东"
    assert {item.kind for item in result.evidence} == {"metric", "query", "result"}
    assert any(item.locator == "row:0/column:change_amount" for item in result.bindings)
