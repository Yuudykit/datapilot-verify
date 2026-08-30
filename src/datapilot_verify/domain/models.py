from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorCode(StrEnum):
    BAD_PARAMS = "BAD_PARAMS"
    NOT_FOUND = "NOT_FOUND"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"


class ToolError(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(BaseModel):
    evidence_id: str
    kind: Literal["dataset", "metric", "document", "query", "result", "code", "chart"]
    label: str
    source: str
    locator: str | None = None
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    artifact_id: str
    kind: Literal["table", "chart", "report", "snapshot", "code"]
    path: Path
    media_type: str
    sha256: str | None = None


class EvidenceBinding(BaseModel):
    claim_key: str
    evidence_id: str
    locator: str
    value: Any


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    bindings: list[EvidenceBinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: ToolError | None = None
    trace_id: str

    @model_validator(mode="after")
    def result_matches_status(self) -> ToolResult:
        if self.ok and self.error is not None:
            raise ValueError("successful ToolResult cannot contain an error")
        if not self.ok and self.error is None:
            raise ValueError("failed ToolResult must contain an error")
        return self


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    nullable: bool
    null_count: int = 0
    distinct_count: int | None = None
    sample_values: list[Any] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    dataset_id: str
    filename: str
    sha256: str
    row_count: int
    columns: list[ColumnProfile]
    time_range: tuple[date, date] | None = None
    warnings: list[str] = Field(default_factory=list)


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    expression: str
    grain: str
    time_dimension: str
    allowed_dimensions: list[str]
    unit: str
    owner: str
    description: str
    version: str
    effective_from: date


class FilterSpec(BaseModel):
    field: str
    operator: Literal["eq", "ne", "in", "between", "gt", "gte", "lt", "lte"]
    value: Any

    @model_validator(mode="after")
    def validate_operator_value(self) -> FilterSpec:
        if self.operator == "between" and (
            not isinstance(self.value, list) or len(self.value) != 2
        ):
            raise ValueError("between requires a two-item list")
        if self.operator == "in" and not isinstance(self.value, list):
            raise ValueError("in requires a list")
        return self


class ComparisonSpec(BaseModel):
    type: Literal["mom", "yoy", "custom"]
    current_period: tuple[date, date]
    previous_period: tuple[date, date]

    @model_validator(mode="after")
    def periods_do_not_overlap(self) -> ComparisonSpec:
        current_start, current_end = self.current_period
        previous_start, previous_end = self.previous_period
        if current_start > current_end or previous_start > previous_end:
            raise ValueError("period start must not be after period end")
        if max(current_start, previous_start) <= min(current_end, previous_end):
            raise ValueError("comparison periods must not overlap")
        return self


class SortSpec(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    dataset_ids: list[str]
    metric: str
    dimensions: list[str] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    comparison: ComparisonSpec | None = None
    analysis: Literal["aggregate", "trend", "ranking", "contribution", "statistical"]
    sort: list[SortSpec] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=1000)
    execution_hint: Literal["auto", "sql", "python"] = "auto"
    question: str

    @model_validator(mode="after")
    def validate_analysis_requirements(self) -> AnalysisPlan:
        if not self.dataset_ids:
            raise ValueError("at least one dataset is required")
        if self.analysis == "contribution" and self.comparison is None:
            raise ValueError("contribution analysis requires a comparison")
        if self.analysis in {"ranking", "contribution"} and not self.dimensions:
            raise ValueError(f"{self.analysis} analysis requires at least one dimension")
        return self


class AnalysisSnapshot(BaseModel):
    snapshot_id: str
    created_at: datetime
    question: str
    dataset_hashes: dict[str, str]
    semantic_version: str
    knowledge_version: str
    plan: AnalysisPlan | None = None
    tool_trace_ids: list[str] = Field(default_factory=list)
    sql: str | None = None
    python_code: str | None = None
    result_hash: str | None = None
    verification: dict[str, Any] = Field(default_factory=dict)
    replay_level: Literal["strong", "best_effort", "not_replayable"]
