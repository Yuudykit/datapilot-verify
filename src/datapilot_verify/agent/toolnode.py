from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from datapilot_verify.agent.model import OpenAIModelAdapter
from datapilot_verify.tools import ToolContext, ToolRegistry


class ToolNodeState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    response_id: str | None
    steps: int


class ToolNodeWorkflow:
    """Bounded LangGraph model/tool loop using the real ToolNode implementation."""

    def __init__(
        self,
        adapter: OpenAIModelAdapter,
        registry: ToolRegistry,
        context: ToolContext,
        *,
        allowed: set[str] | None = None,
        max_steps: int = 8,
        checkpointer: Any | None = None,
    ) -> None:
        self.adapter = adapter
        self.registry = registry
        self.context = context
        self.allowed = allowed
        self.max_steps = max_steps
        builder = StateGraph(ToolNodeState)
        builder.add_node("model", self._model)
        builder.add_node("tools", ToolNode(registry.langchain_tools(context, allowed)))
        builder.add_edge(START, "model")
        builder.add_conditional_edges(
            "model", self._route, {"tools": "tools", "end": END}
        )
        builder.add_edge("tools", "model")
        self.graph = builder.compile(checkpointer=checkpointer)

    def _model(self, state: ToolNodeState) -> dict[str, Any]:
        messages = state.get("messages", [])
        inputs: list[dict[str, Any]] = []
        if state.get("response_id"):
            for message in reversed(messages):
                if not isinstance(message, ToolMessage):
                    break
                inputs.insert(0, {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content
                    if isinstance(message.content, str)
                    else json.dumps(message.content, ensure_ascii=False, default=str),
                })
        else:
            human = next(
                (message for message in reversed(messages) if isinstance(message, HumanMessage)),
                None,
            )
            inputs = [{"role": "user", "content": human.content if human else ""}]
        turn = self.adapter.turn(
            inputs,
            self.registry,
            self.context,
            self.allowed,
            state.get("response_id"),
        )
        tool_calls = [
            {"name": call.name, "args": call.arguments, "id": call.call_id, "type": "tool_call"}
            for call in turn.tool_calls
        ]
        return {
            "messages": [AIMessage(content=turn.text, tool_calls=tool_calls)],
            "response_id": turn.response_id,
            "steps": state.get("steps", 0) + 1,
        }

    def _route(self, state: ToolNodeState) -> str:
        if state.get("steps", 0) >= self.max_steps:
            return "end"
        last = state.get("messages", [])[-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "end"

    def invoke(self, question: str, config: dict[str, Any] | None = None) -> ToolNodeState:
        return self.graph.invoke(
            {"messages": [HumanMessage(content=question)], "steps": 0}, config
        )
