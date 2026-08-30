from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from datapilot_verify.domain.models import (
    ArtifactRef,
    ErrorCode,
    EvidenceRef,
    ToolError,
    ToolResult,
)
from datapilot_verify.engine import enrich_contribution
from datapilot_verify.sandbox import PythonRunner
from datapilot_verify.tools.base import ToolContext, tool


class PythonAnalysisArgs(BaseModel):
    code: str = Field(min_length=1, max_length=20_000)
    dataset: str = "orders.csv"
    repair_candidates: list[str] = Field(default_factory=list, max_length=2)
    timeout_seconds: int = Field(default=15, ge=1, le=60)


class ContributionArgs(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


@tool(
    name="run_python_analysis",
    description=(
        "Run a long-tail analysis in the restricted Python worker, with at most two "
        "supplied repair attempts."
    ),
    args_model=PythonAnalysisArgs,
    stage="analysis",
)
def run_python_analysis(
    *, args: PythonAnalysisArgs, context: ToolContext, trace_id: str
) -> ToolResult:
    dataset = (context.workspace / args.dataset).resolve()
    try:
        dataset.relative_to(context.workspace.resolve())
    except ValueError:
        return ToolResult(
            ok=False,
            error=ToolError(
                code=ErrorCode.POLICY_BLOCKED, message="dataset path escapes workspace"
            ),
            trace_id=trace_id,
        )
    attempts: list[dict[str, Any]] = []
    runner = PythonRunner(timeout_seconds=args.timeout_seconds)
    candidates = [args.code, *args.repair_candidates]
    for index, code in enumerate(candidates):
        try:
            run = runner.run(code, dataset, context.output_dir / "python")
        except ValueError as exc:
            return ToolResult(
                ok=False,
                data={"attempts": attempts},
                error=ToolError(code=ErrorCode.POLICY_BLOCKED, message=str(exc)),
                trace_id=trace_id,
            )
        attempts.append(
            {
                "attempt": index + 1,
                "ok": run.ok,
                "return_code": run.return_code,
                "timed_out": run.timed_out,
                "stderr": run.stderr[-1500:],
            }
        )
        if run.ok:
            code_path = context.output_dir / "python" / f"code_{trace_id}.py"
            code_path.write_text(code, encoding="utf-8")
            digest = hashlib.sha256(code_path.read_bytes()).hexdigest()
            return ToolResult(
                ok=True,
                data={"result": run.result, "stdout": run.stdout, "attempts": attempts},
                artifacts=[
                    ArtifactRef(
                        artifact_id=trace_id,
                        kind="code",
                        path=code_path,
                        media_type="text/x-python",
                        sha256=digest,
                    )
                ],
                evidence=[
                    EvidenceRef(
                        evidence_id=f"code:{trace_id}",
                        kind="code",
                        label="Restricted Python analysis",
                        source=str(code_path),
                        version=digest,
                        metadata={"attempt_count": index + 1, "dataset": args.dataset},
                    )
                ],
                trace_id=trace_id,
            )
    last = attempts[-1] if attempts else {}
    error_code = ErrorCode.TIMEOUT if last.get("timed_out") else ErrorCode.EXECUTION_FAILED
    return ToolResult(
        ok=False,
        data={"attempts": attempts},
        error=ToolError(
            code=error_code,
            message="restricted Python analysis failed after all attempts",
            retryable=False,
            details={"last_stderr": last.get("stderr", "")},
        ),
        trace_id=trace_id,
    )


@tool(
    name="analyze_contribution",
    description="Calculate decline contribution rates from verified comparison rows.",
    args_model=ContributionArgs,
    stage="analysis",
)
def analyze_contribution(
    *, args: ContributionArgs, context: ToolContext, trace_id: str
) -> ToolResult:
    if any("change_amount" not in row for row in args.rows):
        return ToolResult(
            ok=False,
            error=ToolError(
                code=ErrorCode.BAD_PARAMS,
                message="every row must contain change_amount",
            ),
            trace_id=trace_id,
        )
    rows = enrich_contribution(args.rows)
    total = sum(row["decline_contribution_rate"] for row in rows)
    passed = (
        abs(total - 1.0) < 1e-9 if any(row["change_amount"] < 0 for row in rows) else total == 0
    )
    return ToolResult(
        ok=passed,
        data={"rows": rows, "verification": {"passed": passed, "contribution_sum": total}},
        error=None
        if passed
        else ToolError(
            code=ErrorCode.EXECUTION_FAILED, message="contribution rates do not sum to one"
        ),
        trace_id=trace_id,
    )
