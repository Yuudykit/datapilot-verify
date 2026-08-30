from pathlib import Path

from pydantic import BaseModel, model_validator

from datapilot_verify.domain.models import ToolResult
from datapilot_verify.tools import ToolContext, ToolRegistry, tool


class EchoArgs(BaseModel):
    value: str


@tool(name="echo", description="Echo a value", args_model=EchoArgs, stage="test")
def echo(*, args: EchoArgs, context: ToolContext, trace_id: str) -> ToolResult:
    return ToolResult(ok=True, data={"value": args.value}, trace_id=trace_id)


@tool(name="boom", description="Always raises", args_model=EchoArgs, stage="test")
def boom(*, args: EchoArgs, context: ToolContext, trace_id: str) -> ToolResult:
    raise ValueError("sort field is not available: x")


class StrictArgs(BaseModel):
    value: str

    @model_validator(mode="after")
    def _reject(self) -> "StrictArgs":
        raise ValueError("bad combination")


@tool(name="strict", description="Rejects", args_model=StrictArgs, stage="test")
def strict(*, args: StrictArgs, context: ToolContext, trace_id: str) -> ToolResult:
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


def test_registry_internal_error_keeps_exception_detail(tmp_path) -> None:
    # 模型自纠依赖失败原因：INTERNAL 报错必须携带底层异常信息（BUG-025）。
    registry = ToolRegistry()
    registry.register(boom)
    result = registry.execute("boom", {"value": "x"}, context(tmp_path))
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "INTERNAL"
    assert "sort field is not available: x" in result.error.message


def test_registry_bad_params_details_stay_json_serializable(tmp_path) -> None:
    # 校验错误的 details 里不得残留异常实例（ctx），否则
    # model_dump(mode="json") 自身会抛 PydanticSerializationError（BUG-026）。
    registry = ToolRegistry()
    registry.register(strict)
    result = registry.execute("strict", {"value": "x"}, context(tmp_path))
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "BAD_PARAMS"
    payload = result.model_dump(mode="json")
    first_error = payload["error"]["details"]["errors"][0]
    assert first_error["msg"].endswith("bad combination")
    assert "ctx" not in first_error


def test_registry_adapts_tools_for_langgraph_toolnode(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(echo)
    adapters = registry.langchain_tools(context(tmp_path), allowed={"echo"})
    assert [item.name for item in adapters] == ["echo"]
    payload = adapters[0].invoke({"value": "through-toolnode"})
    assert payload["ok"] is True
    assert payload["data"] == {"value": "through-toolnode"}
