from datetime import date
from pathlib import Path

import pytest

from datapilot_verify.compiler import PlanCompiler
from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, SortSpec
from datapilot_verify.semantic import SemanticRepository

ROOT = Path(__file__).resolve().parents[1]


def test_compiles_parameterized_contribution_query(monkeypatch) -> None:
    compiler = PlanCompiler()
    monkeypatch.setattr(compiler.policy, "validate", lambda sql: None)
    metric = SemanticRepository(ROOT / "data" / "semantic" / "metrics.yml").get("net_sales")
    assert metric is not None
    plan = AnalysisPlan(
        plan_id="plan_contribution",
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
        question="why did net sales decline",
    )
    compiled = compiler.compile(plan, metric)
    assert "FULL OUTER JOIN" in compiled.sql
    assert "change_amount" in compiled.sql
    assert compiled.parameters[:4] == [
        date(2026, 7, 1),
        date(2026, 7, 31),
        date(2026, 6, 1),
        date(2026, 6, 30),
    ]


def test_rejects_dimension_not_allowed_by_metric(monkeypatch) -> None:
    compiler = PlanCompiler()
    monkeypatch.setattr(compiler.policy, "validate", lambda sql: None)
    metric = SemanticRepository(ROOT / "data" / "semantic" / "metrics.yml").get("net_sales")
    assert metric is not None
    plan = AnalysisPlan(
        plan_id="bad",
        dataset_ids=["orders"],
        metric="net_sales",
        dimensions=["unknown"],
        analysis="ranking",
        question="bad dimension",
    )
    with pytest.raises(ValueError, match="not allowed"):
        compiler.compile(plan, metric)

