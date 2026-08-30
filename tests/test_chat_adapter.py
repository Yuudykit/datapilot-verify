from pathlib import Path
from types import SimpleNamespace

from datapilot_verify.agent import ChatToolLoop, OpenAIChatAdapter
from datapilot_verify.app import build_registry
from datapilot_verify.tools import ToolContext

ROOT = Path(__file__).resolve().parents[1]


class FakeChat:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            fn = SimpleNamespace(name="inspect_dataset", arguments='{"path":"orders.csv"}')
            message = SimpleNamespace(
                content=None, tool_calls=[SimpleNamespace(id="c1", function=fn)]
            )
        else:
            message = SimpleNamespace(content="完成", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_chat_completions_loop_round_trips_tool_result(tmp_path: Path) -> None:
    fake = FakeChat()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake.create)))
    registry = build_registry(ROOT)
    loop = ChatToolLoop(
        OpenAIChatAdapter(client, "fake"),
        registry,
        ToolContext("test", ROOT / "data" / "sample", tmp_path),
        max_steps=3,
    )
    result = loop.run("检查订单数据", allowed={"inspect_dataset"})
    assert result["status"] == "completed"
    assert result["tool_trace"][0]["name"] == "inspect_dataset"


class MalformedJsonThenTextChat:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            fn = SimpleNamespace(name="inspect_dataset", arguments="{bad json")
            message = SimpleNamespace(
                content=None, tool_calls=[SimpleNamespace(id="bad", function=fn)]
            )
        else:
            message = SimpleNamespace(content="已按有效结果作答", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_chat_loop_survives_malformed_tool_arguments(tmp_path: Path) -> None:
    fake = MalformedJsonThenTextChat()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake.create)))
    loop = ChatToolLoop(
        OpenAIChatAdapter(client, "fake"),
        build_registry(ROOT),
        ToolContext("test", ROOT / "data" / "sample", tmp_path),
        max_steps=3,
    )
    result = loop.run("检查订单数据", allowed={"inspect_dataset"})
    assert result["status"] == "completed"
    assert result["answer"] == "已按有效结果作答"
    failed = result["tool_trace"][0]["result"]
    assert failed["ok"] is False
    assert failed["error"]["code"] == "BAD_PARAMS"
    assert "malformed JSON" in failed["error"]["message"]


class RepeatingToolChat:
    def create(self, **kwargs):
        if "tools" not in kwargs:
            message = SimpleNamespace(content="根据已有结果完成总结", tool_calls=[])
        else:
            fn = SimpleNamespace(name="inspect_dataset", arguments='{"path":"orders.csv"}')
            message = SimpleNamespace(
                content=None, tool_calls=[SimpleNamespace(id="repeat", function=fn)]
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_chat_loop_finalizes_without_tools_at_budget_limit(tmp_path: Path) -> None:
    fake = RepeatingToolChat()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake.create)))
    loop = ChatToolLoop(
        OpenAIChatAdapter(client, "fake"),
        build_registry(ROOT),
        ToolContext("test", ROOT / "data" / "sample", tmp_path),
        max_steps=1,
    )
    result = loop.run("检查订单数据", allowed={"inspect_dataset"})
    assert result["status"] == "completed"
    assert result["tool_budget_exhausted"] is True
    assert result["answer"] == "根据已有结果完成总结"
