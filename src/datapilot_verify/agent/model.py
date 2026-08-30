from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from datapilot_verify.domain.models import ErrorCode, ToolError, ToolResult
from datapilot_verify.tools import ToolContext, ToolRegistry

SYSTEM_PROMPT = (
    "你是 DataPilot Verify 经营分析 Agent。\n"
    "授权工作区包含 orders.csv 和 stores.csv。所有数据事实、指标口径和计算结果必须通过 "
    "提供的 Tool 获取；"
    "不得自行编造数值。\n"
    "优先使用 SQL 分析工具，只有统计检验或 SQL 不适合的长尾任务才使用受控 Python。"
    "回答应简洁，并区分算术贡献与因果关系。已有足够证据后立即作答，不要重复调用 Tool。"
)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    arguments_error: str | None = None


@dataclass(frozen=True)
class ModelTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    response_id: str | None = None


def _parse_arguments(call_id: str, name: str, raw: Any) -> ToolCall:
    """模型输出的 arguments 可能不是合法 JSON（BUG-015）；解析失败时记录
    错误而不是让整个会话崩溃，由工具循环把它作为失败结果回传给模型重试。"""
    if isinstance(raw, str):
        try:
            return ToolCall(call_id=call_id, name=name, arguments=json.loads(raw))
        except json.JSONDecodeError as exc:
            return ToolCall(
                call_id=call_id, name=name, arguments={}, arguments_error=str(exc)
            )
    return ToolCall(call_id=call_id, name=name, arguments=raw)


def _invalid_arguments_result(call: ToolCall) -> dict[str, Any]:
    result = ToolResult(
        ok=False,
        error=ToolError(
            code=ErrorCode.BAD_PARAMS,
            message=(
                f"model emitted malformed JSON arguments for tool {call.name}: "
                f"{call.arguments_error}"
            ),
        ),
        trace_id=f"tool_{uuid.uuid4().hex[:12]}",
    )
    return {"call_id": call.call_id, "name": call.name, "result": result.model_dump(mode="json")}


class ResponsesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class OpenAIModelAdapter:
    """Thin Responses API adapter; execution remains inside ToolRegistry."""

    def __init__(self, client: Any, model: str = "gpt-5-mini") -> None:
        self.client = client
        self.model = model

    def turn(
        self,
        messages: list[dict[str, Any]],
        registry: ToolRegistry,
        context: ToolContext,
        allowed: set[str] | None = None,
        previous_response_id: str | None = None,
    ) -> ModelTurn:
        response_tools = [
            {"type": "function", **schema["function"]} for schema in registry.schemas(allowed)
        ]
        request = {
            "model": self.model,
            "input": messages,
            "tools": response_tools,
        }
        if previous_response_id:
            request["previous_response_id"] = previous_response_id
        response = self.client.responses.create(
            **request,
        )
        calls: list[ToolCall] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            calls.append(
                _parse_arguments(
                    call_id=getattr(item, "call_id", getattr(item, "id", "")),
                    name=item.name,
                    raw=getattr(item, "arguments", "{}"),
                )
            )
        return ModelTurn(
            text=getattr(response, "output_text", "") or "",
            tool_calls=calls,
            response_id=getattr(response, "id", None),
        )

    def execute_calls(
        self,
        turn: ModelTurn,
        registry: ToolRegistry,
        context: ToolContext,
        allowed: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for call in turn.tool_calls:
            if call.arguments_error is not None:
                outputs.append(_invalid_arguments_result(call))
                continue
            outputs.append(
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "result": registry.execute(
                        call.name, call.arguments, context, allowed
                    ).model_dump(mode="json"),
                }
            )
        return outputs


class ModelToolLoop:
    def __init__(
        self,
        adapter: OpenAIModelAdapter,
        registry: ToolRegistry,
        context: ToolContext,
        max_steps: int = 8,
    ) -> None:
        self.adapter = adapter
        self.registry = registry
        self.context = context
        self.max_steps = max_steps

    def run(self, question: str, allowed: set[str] | None = None) -> dict[str, Any]:
        inputs: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        previous_response_id = None
        trace: list[dict[str, Any]] = []
        for step in range(1, self.max_steps + 1):
            turn = self.adapter.turn(
                inputs, self.registry, self.context, allowed, previous_response_id
            )
            if not turn.tool_calls:
                return {
                    "status": "completed",
                    "answer": turn.text,
                    "steps": step,
                    "tool_trace": trace,
                }
            outputs = self.adapter.execute_calls(turn, self.registry, self.context, allowed)
            trace.extend(outputs)
            inputs = [
                {
                    "type": "function_call_output",
                    "call_id": item["call_id"],
                    "output": json.dumps(item["result"], ensure_ascii=False, default=str),
                }
                for item in outputs
            ]
            previous_response_id = turn.response_id
        return {
            "status": "budget_exhausted",
            "answer": "模型工具调用达到最大步数，工作流已停止。",
            "steps": self.max_steps,
            "tool_trace": trace,
        }


class OpenAIChatAdapter:
    """Chat Completions adapter for providers without Responses tool replay."""

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def turn(
        self,
        messages: list[dict[str, Any]],
        registry: ToolRegistry,
        allowed: set[str] | None = None,
    ) -> tuple[ModelTurn, Any]:
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=registry.schemas(allowed)
        )
        message = response.choices[0].message
        calls = [
            _parse_arguments(
                call_id=item.id, name=item.function.name, raw=item.function.arguments
            )
            for item in (message.tool_calls or [])
        ]
        return ModelTurn(text=message.content or "", tool_calls=calls), message

    def finalize(self, messages: list[dict[str, Any]]) -> str:
        final_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "工具调用额度已用完。请只根据上面的成功 Tool 结果给出简洁结论；"
                    "不得再调用工具，不得补充未被证据支持的数值。"
                ),
            },
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=final_messages,
        )
        return response.choices[0].message.content or ""


class ChatToolLoop:
    def __init__(
        self,
        adapter: OpenAIChatAdapter,
        registry: ToolRegistry,
        context: ToolContext,
        max_steps: int = 8,
    ) -> None:
        self.adapter = adapter
        self.registry = registry
        self.context = context
        self.max_steps = max_steps

    def run(self, question: str, allowed: set[str] | None = None) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        trace: list[dict[str, Any]] = []
        for step in range(1, self.max_steps + 1):
            turn, assistant = self.adapter.turn(messages, self.registry, allowed)
            if not turn.tool_calls:
                return {
                    "status": "completed",
                    "answer": turn.text,
                    "steps": step,
                    "tool_trace": trace,
                }
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant.content,
                    "tool_calls": [
                        {
                            "id": item.id,
                            "type": "function",
                            "function": {
                                "name": item.function.name,
                                "arguments": item.function.arguments,
                            },
                        }
                        for item in (assistant.tool_calls or [])
                    ],
                }
            )
            for call in turn.tool_calls:
                if call.arguments_error is not None:
                    payload = _invalid_arguments_result(call)["result"]
                    trace.append(
                        {"call_id": call.call_id, "name": call.name, "result": payload}
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "content": json.dumps(
                                payload, ensure_ascii=False, default=str
                            ),
                        }
                    )
                    continue
                result = self.registry.execute(call.name, call.arguments, self.context, allowed)
                payload = result.model_dump(mode="json")
                trace.append({"call_id": call.call_id, "name": call.name, "result": payload})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "content": json.dumps(payload, ensure_ascii=False, default=str),
                    }
                )
        try:
            answer = self.adapter.finalize(messages)
        except Exception:
            answer = ""
        if answer:
            return {
                "status": "completed",
                "answer": answer,
                "steps": self.max_steps,
                "tool_trace": trace,
                "tool_budget_exhausted": True,
            }
        return {
            "status": "budget_exhausted",
            "answer": "模型工具调用达到最大步数，工作流已停止。",
            "steps": self.max_steps,
            "tool_trace": trace,
        }


def build_live_tool_loop(
    project_root: Path,
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    max_steps: int = 8,
    workspace: Path | None = None,
    output_dir: Path | None = None,
) -> Any:
    from openai import OpenAI

    from datapilot_verify.app import build_registry

    root = project_root.resolve()
    client = OpenAI(api_key=api_key, base_url=base_url)
    context = ToolContext(
        "live",
        (workspace or root / "data" / "sample").resolve(),
        (output_dir or root / "artifacts" / "live").resolve(),
    )
    context.output_dir.mkdir(parents=True, exist_ok=True)
    registry = build_registry(root)
    if "deepseek" in (base_url or "").casefold():
        return ChatToolLoop(OpenAIChatAdapter(client, model), registry, context, max_steps)
    return ModelToolLoop(OpenAIModelAdapter(client, model), registry, context, max_steps)
