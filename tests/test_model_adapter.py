from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel

from datapilot_verify.agent.model import ModelToolLoop, OpenAIModelAdapter
from datapilot_verify.domain.models import ToolResult
from datapilot_verify.tools import ToolContext, ToolRegistry, tool


class EchoArgs(BaseModel):
    value: str


@tool(name="echo", description="Echo", args_model=EchoArgs, stage="test")
def echo(*, args: EchoArgs, context: ToolContext, trace_id: str) -> ToolResult:
    return ToolResult(ok=True, data={"value": args.value}, trace_id=trace_id)


class FakeResponses:
    def __init__(self) -> None:
        self.request = None
        self.calls = 0

    def create(self, **kwargs):
        self.request = kwargs
        self.calls += 1
        if self.calls > 1:
            return SimpleNamespace(output=[], output_text="工具结果已处理")
        call = SimpleNamespace(
            type="function_call",
            call_id="call_1",
            name="echo",
            arguments='{"value":"hello"}',
        )
        return SimpleNamespace(output=[call], output_text="")


class MalformedResponses:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls > 1:
            return SimpleNamespace(output=[], output_text="已纠正后作答")
        call = SimpleNamespace(
            type="function_call",
            call_id="call_bad",
            name="echo",
            arguments='{"value": ',
        )
        return SimpleNamespace(output=[call], output_text="")


def test_responses_adapter_survives_malformed_tool_arguments(tmp_path: Path) -> None:
    client = SimpleNamespace(responses=MalformedResponses())
    registry = ToolRegistry()
    registry.register(echo)
    context = ToolContext("test", tmp_path, tmp_path)
    loop = ModelToolLoop(
        OpenAIModelAdapter(client, model="test-model"), registry, context, max_steps=3
    )
    result = loop.run("echo hello", allowed={"echo"})
    assert result["status"] == "completed"
    assert result["answer"] == "已纠正后作答"
    failed = result["tool_trace"][0]["result"]
    assert failed["ok"] is False
    assert failed["error"]["code"] == "BAD_PARAMS"
    assert "malformed JSON" in failed["error"]["message"]


def test_openai_adapter_parses_and_executes_tool_calls(tmp_path: Path) -> None:
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    registry = ToolRegistry()
    registry.register(echo)
    context = ToolContext("test", tmp_path, tmp_path)
    adapter = OpenAIModelAdapter(client, model="test-model")
    turn = adapter.turn([{"role": "user", "content": "echo hello"}], registry, context)
    outputs = adapter.execute_calls(turn, registry, context, allowed={"echo"})
    assert responses.request["tools"][0]["name"] == "echo"
    assert outputs[0]["result"]["data"] == {"value": "hello"}
    loop = ModelToolLoop(
        OpenAIModelAdapter(SimpleNamespace(responses=FakeResponses()), model="test-model"),
        registry,
        context,
        max_steps=3,
    )
    final = loop.run("echo hello", allowed={"echo"})
    assert final["status"] == "completed"
    assert final["tool_trace"]
