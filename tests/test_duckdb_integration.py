import json
from datetime import date
from pathlib import Path

from datapilot_verify.compiler import PlanCompiler, SqlPolicy
from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, SortSpec
from datapilot_verify.engine import DuckDBEngine
from datapilot_verify.semantic import SemanticRepository

ROOT = Path(__file__).resolve().parents[1]


def contribution_plan() -> AnalysisPlan:
    return AnalysisPlan(
        plan_id="plan_region_contribution",
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
        question="7 月净销售额为什么下降？",
    )


def test_sql_policy_blocks_non_select() -> None:
    policy = SqlPolicy()
    try:
        policy.validate("DROP TABLE orders")
    except ValueError as exc:
        assert "SELECT" in str(exc) or "blocked" in str(exc)
    else:
        raise AssertionError("DROP should be rejected")


def test_executes_contribution_plan_against_golden_data() -> None:
    semantic = SemanticRepository(ROOT / "data" / "semantic" / "metrics.yml")
    metric = semantic.get("net_sales")
    assert metric is not None
    query = PlanCompiler().compile(contribution_plan(), metric)
    result = DuckDBEngine(ROOT / "data" / "sample").execute(query)
    expected = json.loads(
        (ROOT / "data" / "golden" / "expected_metrics.json").read_text(encoding="utf-8")
    )
    assert result.row_count == 4
    assert result.rows[0]["region"] == expected["largest_decline_region"]
    assert result.rows[0]["change_amount"] == expected["region_changes"]["华东"]
    assert len(result.result_hash) == 64

