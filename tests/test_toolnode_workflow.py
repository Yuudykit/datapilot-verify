from pathlib import Path
from types import SimpleNamespace

from datapilot_verify.agent import OpenAIModelAdapter, ToolNodeWorkflow
from datapilot_verify.app import build_registry
from datapilot_verify.tools import ToolContext

ROOT = Path(__file__).resolve().parents[1]


class FakeResponses:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            item = SimpleNamespace(
                type="function_call", call_id="inspect_1", name="inspect_dataset",
                arguments='{"path":"orders.csv"}',
            )
            return SimpleNamespace(id="response_1", output=[item], output_text="")
        return SimpleNamespace(id="response_2", output=[], output_text="数据检查已完成")


def test_real_toolnode_executes_registry_tool(tmp_path: Path) -> None:
    responses = FakeResponses()
    adapter = OpenAIModelAdapter(SimpleNamespace(responses=responses), model="fake")
    registry = build_registry(ROOT)
    context = ToolContext("toolnode", ROOT / "data" / "sample", tmp_path)
    workflow = ToolNodeWorkflow(
        adapter, registry, context, allowed={"inspect_dataset"}, max_steps=3
    )
    result = workflow.invoke("检查订单数据", {"configurable": {"thread_id": "toolnode-test"}})
    assert result["steps"] == 2
    assert result["messages"][-1].content == "数据检查已完成"
    assert result["messages"][2].type == "tool"
