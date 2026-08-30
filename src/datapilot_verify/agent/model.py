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
    "授权工作区已导入 orders.csv（订单明细）和 stores.csv（门店维表），两表已可按 "
    "store_id 关联；不要调用 register_dataset / define_relationship，除非用户明确要求"
    "注册或检查数据集。\n"
    "所有数据事实、指标口径和计算结果必须通过 Tool 获取，不得自行编造数值。\n"
    "工具选择：数据行数/字段/质量用 inspect_dataset；指标定义与口径用 resolve_metric 和 "
    "search_metric_docs；指标环比对比与归因一律用 run_analysis（metric 传 metric_id，"
    "如 net_sales / refund_rate / avg_order_value）；只有 SQL 无法完成的长尾任务才用 "
    "run_python_analysis，读取数据只能写 pd.read_csv(input_csv)：input_csv 是文件路径"
    "而不是 DataFrame，也不要用 str() 包裹。\n"
    "run_analysis 的 plan 参数示例（期间按问题中的月份取整月）：\n"
    '{"plan_id": "plan_x1", "dataset_ids": ["orders", "stores"], "metric": "net_sales", '
    '"dimensions": ["region"], "comparison": {"type": "mom", '
    '"current_period": ["2026-07-01", "2026-07-31"], '
    '"previous_period": ["2026-06-01", "2026-06-30"]}, '
    '"analysis": "contribution", '
    '"sort": [{"field": "change_amount", "direction": "asc"}], '
    '"question": "7月净销售额为什么下降"}\n'
    "回答应简洁，并区分算术贡献与因果关系。已有足够证据后立即作答，不要重复调用 Tool。"
)

FINALIZE_PROMPT = (
    "工具调用额度已用完。请只根据上面的成功 Tool 结果给出简洁结论；"
    "不得再调用工具，不得补充未被证据支持的数值。"
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

    def finalize(
        self, inputs: list[dict[str, Any]], previous_response_id: str | None = None
    ) -> str:
        """步数用尽后的兜底总结：不带 tools 再问一次，只基于已有工具结果作答。"""
        response = self.client.responses.create(
            model=self.model,
            input=[*inputs, {"role": "user", "content": FINALIZE_PROMPT}],
            previous_response_id=previous_response_id,
        )
        return getattr(response, "output_text", "") or ""

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
        try:
            answer = self.adapter.finalize(inputs, previous_response_id)
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
        final_messages = [*messages, {"role": "user", "content": FINALIZE_PROMPT}]
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
