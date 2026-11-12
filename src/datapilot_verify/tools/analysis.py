from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from datapilot_verify.compiler import PlanCompiler
from datapilot_verify.domain.models import (
    AnalysisPlan,
    ErrorCode,
    EvidenceBinding,
    EvidenceRef,
    ToolError,
    ToolResult,
)
from datapilot_verify.engine import DuckDBEngine, InvalidStoreData, enrich_contribution
from datapilot_verify.semantic import SemanticRepository
from datapilot_verify.tools.base import Tool, ToolContext, tool
from datapilot_verify.verification import verify_comparison_rows


class RunAnalysisArgs(BaseModel):
    plan: AnalysisPlan


def build_run_analysis_tool(semantic_path: Path) -> Tool:
    semantic = SemanticRepository(semantic_path)

    @tool(
        name="run_analysis",
        description="Validate and execute a structured business analysis plan with DuckDB.",
        args_model=RunAnalysisArgs,
        stage="analysis",
    )
    def run_analysis(*, args: RunAnalysisArgs, context: ToolContext, trace_id: str) -> ToolResult:
        metric = semantic.get(args.plan.metric)
        if metric is None:
            raise ValueError(f"unknown metric: {args.plan.metric}")
        compiled = PlanCompiler().compile(args.plan, metric)
        engine = DuckDBEngine(context.workspace)
        overall_compiled = None
        if args.plan.comparison is not None and args.plan.dimensions:
            overall_plan = args.plan.model_copy(
                update={"dimensions": [], "analysis": "aggregate", "sort": [], "limit": None}
            )
            overall_compiled = PlanCompiler().compile(overall_plan, metric)
        try:
            result = engine.execute(compiled)
            overall_result = engine.execute(overall_compiled) if overall_compiled else None
        except InvalidStoreData as exc:
            return ToolResult(
                ok=False,
                error=ToolError(code=ErrorCode.EXECUTION_FAILED, message=str(exc)),
                trace_id=trace_id,
            )
        rows = result.rows
        overall = overall_result.rows[0] if overall_result and overall_result.rows else None
        verification = None
        if args.plan.comparison is not None:
            verification = verify_comparison_rows(rows)
            if args.plan.analysis == "contribution":
                rows = enrich_contribution(rows)
        result_evidence_id = f"result:{result.result_hash[:16]}"
        evidence = [
            EvidenceRef(
                evidence_id=f"metric:{metric.metric_id}:{metric.version}",
                kind="metric",
                label=metric.name,
                source=str(semantic.path),
                version=metric.version,
            ),
            EvidenceRef(
                evidence_id=f"query:{trace_id}",
                kind="query",
                label="Compiled read-only SQL",
                source="DuckDB",
                metadata={
                    "sql": compiled.sql,
                    "parameters": [str(item) for item in compiled.parameters],
                    "overall_sql": overall_compiled.sql if overall_compiled else None,
                },
            ),
            EvidenceRef(
                evidence_id=result_evidence_id,
                kind="result",
                label=f"Analysis result ({result.row_count} rows)",
                source=trace_id,
                version=result.result_hash,
            ),
        ]
        warnings = list(verification.warnings) if verification else []
        bindings = [
            EvidenceBinding(
                claim_key=f"row_{row_index}.{field}",
                evidence_id=result_evidence_id,
                locator=f"row:{row_index}/column:{field}",
                value=value,
            )
            for row_index, row in enumerate(rows)
            for field, value in row.items()
            if field
            in {
                "value",
                "current_value",
                "previous_value",
                "change_amount",
                "change_rate",
                "decline_contribution_rate",
            }
        ]
        return ToolResult(
            ok=verification.passed if verification else True,
            data={
                "plan_id": args.plan.plan_id,
                "plan": args.plan.model_dump(mode="json"),
                "metric": metric.model_dump(mode="json"),
                "semantic_hash": semantic.content_hash,
                "rows": rows,
                "overall": overall,
                "row_count": result.row_count,
                "result_hash": result.result_hash,
                "verification": (
                    {"passed": verification.passed, "checks": verification.checks}
                    if verification
                    else {"passed": True, "checks": {}}
                ),
            },
            evidence=evidence,
            bindings=bindings,
            warnings=warnings,
            error=(
                ToolError(code=ErrorCode.EXECUTION_FAILED, message="数值校验失败。")
                if verification and not verification.passed
                else None
            ),
            trace_id=trace_id,
        )

    return run_analysis
