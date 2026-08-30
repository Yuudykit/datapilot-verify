from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from datapilot_verify.app import build_registry
from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, SortSpec
from datapilot_verify.tools import ToolContext

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class EvalReport:
    total: int
    passed: int
    metric_resolution_accuracy: float
    retrieval_recall_at_5: float
    execution_accuracy: float
    numeric_faithfulness: float
    details: list[dict[str, object]]


def run_eval(project_root: Path = ROOT) -> EvalReport:
    registry = build_registry(project_root)
    context = ToolContext(
        session_id="eval",
        workspace=project_root / "data" / "sample",
        output_dir=project_root / "artifacts" / "eval",
    )
    expected = json.loads(
        (project_root / "data" / "golden" / "expected_metrics.json").read_text(encoding="utf-8")
    )
    details: list[dict[str, object]] = []

    metric_cases = [
        ("净销售额", "net_sales"),
        ("净GMV", "net_sales"),
        ("退款率", "refund_rate"),
        ("AOV", "avg_order_value"),
    ]
    metric_passed = 0
    for query, expected_metric in metric_cases:
        result = registry.execute("resolve_metric", {"query": query}, context)
        actual = result.data.get("matches", [{}])[0].get("metric", {}).get("metric_id")
        passed = result.ok and actual == expected_metric
        metric_passed += int(passed)
        details.append({"kind": "metric", "query": query, "passed": passed, "actual": actual})

    retrieval_cases = [
        ("净销售额是否扣除退款", "01_核心指标口径.md"),
        ("净销售额历史口径变更", "02_口径变更记录.md"),
        ("退款率按订单数还是金额", "01_核心指标口径.md"),
    ]
    retrieval_passed = 0
    for query, expected_source in retrieval_cases:
        result = registry.execute("search_metric_docs", {"query": query, "top_k": 5}, context)
        sources = [item.source for item in result.evidence]
        passed = result.ok and expected_source in sources
        retrieval_passed += int(passed)
        details.append({"kind": "retrieval", "query": query, "passed": passed, "sources": sources})

    plan = AnalysisPlan(
        plan_id="eval_contribution",
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
    analysis = registry.execute("run_analysis", {"plan": plan.model_dump(mode="json")}, context)
    rows = analysis.data.get("rows", [])
    execution_passed = bool(
        analysis.ok
        and rows
        and rows[0]["region"] == expected["largest_decline_region"]
        and rows[0]["change_amount"] == expected["region_changes"]["华东"]
    )
    numeric_passed = bool(analysis.data.get("verification", {}).get("passed"))
    details.append(
        {
            "kind": "analysis",
            "query": plan.question,
            "passed": execution_passed and numeric_passed,
            "top_row": rows[0] if rows else None,
        }
    )
    passed = metric_passed + retrieval_passed + int(execution_passed and numeric_passed)
    total = len(metric_cases) + len(retrieval_cases) + 1
    return EvalReport(
        total=total,
        passed=passed,
        metric_resolution_accuracy=metric_passed / len(metric_cases),
        retrieval_recall_at_5=retrieval_passed / len(retrieval_cases),
        execution_accuracy=float(execution_passed),
        numeric_faithfulness=float(numeric_passed),
        details=details,
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = run_eval()
    output_dir = ROOT / "artifacts" / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "latest.json"
    output.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    if report.passed != report.total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

