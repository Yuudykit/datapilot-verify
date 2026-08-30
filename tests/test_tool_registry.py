from pathlib import Path

from pydantic import BaseModel

from datapilot_verify.domain.models import ToolResult
from datapilot_verify.tools import ToolContext, ToolRegistry, tool


class EchoArgs(BaseModel):
    value: str


@tool(name="echo", description="Echo a value", args_model=EchoArgs, stage="test")
def echo(*, args: EchoArgs, context: ToolContext, trace_id: str) -> ToolResult:
    return ToolResult(ok=True, data={"value": args.value}, trace_id=trace_id)


def context(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="test", workspace=tmp_path, output_dir=tmp_path)


def test_registry_executes_validated_tool(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(echo)
    result = registry.execute("echo", {"value": "ok"}, context(tmp_path))
    assert result.ok
    assert result.data == {"value": "ok"}


def test_registry_rejects_tool_outside_stage_allowlist(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(echo)
    result = registry.execute("echo", {"value": "no"}, context(tmp_path), allowed=set())
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "POLICY_BLOCKED"


def test_registry_normalizes_bad_arguments(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(echo)
    result = registry.execute("echo", {}, context(tmp_path))
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "BAD_PARAMS"


def test_registry_adapts_tools_for_langgraph_toolnode(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(echo)
    adapters = registry.langchain_tools(context(tmp_path), allowed={"echo"})
    assert [item.name for item in adapters] == ["echo"]
    payload = adapters[0].invoke({"value": "through-toolnode"})
    assert payload["ok"] is True
    assert payload["data"] == {"value": "through-toolnode"}
