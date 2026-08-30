from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from datapilot_verify.app import build_registry
from datapilot_verify.domain.models import AnalysisPlan, ComparisonSpec, SortSpec
from datapilot_verify.tools import ToolContext


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    registry = build_registry(ROOT)
    context = ToolContext(
        session_id="demo",
        workspace=ROOT / "data" / "sample",
        output_dir=ROOT / "artifacts" / "demo",
    )
    context.output_dir.mkdir(parents=True, exist_ok=True)

    metric = registry.execute(
        "resolve_metric", {"query": "净GMV为什么下降"}, context, allowed={"resolve_metric"}
    )
    docs = registry.execute(
        "search_metric_docs",
        {"query": "净销售额是否扣除退款，历史口径何时变更", "top_k": 3},
        context,
        allowed={"search_metric_docs"},
    )
    plan = AnalysisPlan(
        plan_id="demo_region_contribution",
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
    analysis = registry.execute(
        "run_analysis",
        {"plan": plan.model_dump(mode="json")},
        context,
        allowed={"run_analysis"},
    )
    payload = {
        "question": plan.question,
        "tool_timeline": [
            {"tool": "resolve_metric", "trace_id": metric.trace_id, "ok": metric.ok},
            {"tool": "search_metric_docs", "trace_id": docs.trace_id, "ok": docs.ok},
            {"tool": "run_analysis", "trace_id": analysis.trace_id, "ok": analysis.ok},
        ],
        "metric": metric.data.get("matches", [{}])[0],
        "citations": [item.model_dump(mode="json") for item in docs.evidence],
        "analysis": analysis.data,
    }
    output = context.output_dir / "demo_result.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n演示结果已保存：{output}")


if __name__ == "__main__":
    main()

