from __future__ import annotations

from pydantic import BaseModel, Field

from datapilot_verify.data import DatasetCatalog, WorkspaceRegistry
from datapilot_verify.domain.models import EvidenceRef, ToolResult
from datapilot_verify.tools.base import ToolContext, tool


class InspectDatasetArgs(BaseModel):
    path: str = Field(min_length=1, max_length=260)


class RegisterDatasetArgs(BaseModel):
    path: str = Field(min_length=1, max_length=260)


class RelationshipArgs(BaseModel):
    left_dataset: str
    left_column: str
    right_dataset: str
    right_column: str


@tool(
    name="inspect_dataset",
    description=(
        "Inspect an authorized CSV or Excel dataset and return its schema and quality profile."
    ),
    args_model=InspectDatasetArgs,
    stage="data",
)
def inspect_dataset(*, args: InspectDatasetArgs, context: ToolContext, trace_id: str) -> ToolResult:
    profile = DatasetCatalog(context.workspace).profile(args.path)
    evidence = EvidenceRef(
        evidence_id=f"dataset:{profile.dataset_id}:{profile.sha256[:12]}",
        kind="dataset",
        label=profile.filename,
        source=args.path,
        version=profile.sha256,
    )
    return ToolResult(
        ok=True,
        data={"profile": profile.model_dump(mode="json")},
        evidence=[evidence],
        trace_id=trace_id,
    )


@tool(
    name="register_dataset",
    description=(
        "Register and hash an uploaded CSV or Excel file in the authorized session workspace."
    ),
    args_model=RegisterDatasetArgs,
    stage="data",
)
def register_dataset(
    *, args: RegisterDatasetArgs, context: ToolContext, trace_id: str
) -> ToolResult:
    profile = WorkspaceRegistry(context.workspace).register(args.path)
    return ToolResult(ok=True, data={"profile": profile}, trace_id=trace_id)


@tool(
    name="define_relationship",
    description="Declare a validated relationship between columns of two registered datasets.",
    args_model=RelationshipArgs,
    stage="data",
)
def define_relationship(
    *, args: RelationshipArgs, context: ToolContext, trace_id: str
) -> ToolResult:
    relationship = WorkspaceRegistry(context.workspace).add_relationship(**args.model_dump())
    return ToolResult(ok=True, data={"relationship": relationship}, trace_id=trace_id)
