from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from datapilot_verify.domain.models import ErrorCode, ToolError, ToolResult

try:
    from opentelemetry import trace

    TRACER = trace.get_tracer("datapilot_verify.tools")
except ImportError:  # pragma: no cover - optional observability dependency
    TRACER = None


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    workspace: Path
    output_dir: Path


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., ToolResult]
    stage: str

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool_definition: Tool) -> None:
        if tool_definition.name in self._tools:
            raise ValueError(f"tool already registered: {tool_definition.name}")
        self._tools[tool_definition.name] = tool_definition

    def names(self, stage: str | None = None) -> list[str]:
        return sorted(
            name for name, item in self._tools.items() if stage is None or item.stage == stage
        )

    def schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        tools = self._tools.values()
        if allowed is not None:
            tools = (item for item in tools if item.name in allowed)
        return [item.schema() for item in tools]

    def langchain_tools(
        self, context: ToolContext, allowed: set[str] | None = None
    ) -> list[Any]:
        """Expose registered tools to LangGraph's ToolNode without bypassing policy.

        The adapter returns JSON-serializable ToolResult payloads and routes every
        invocation back through this registry, preserving Pydantic validation,
        stage allowlists, trace IDs, and the common error boundary.
        """
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("langchain-core is required for ToolNode integration") from exc

        adapters: list[Any] = []
        for name in self.names():
            item = self._tools[name]
            if allowed is not None and name not in allowed:
                continue

            def invoke(_name: str = name, **payload: Any) -> dict[str, Any]:
                result = self.execute(_name, payload, context, allowed=allowed)
                return result.model_dump(mode="json")

            adapters.append(
                StructuredTool.from_function(
                    func=invoke,
                    name=item.name,
                    description=item.description,
                    args_schema=item.args_model,
                )
            )
        return adapters

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        allowed: set[str] | None = None,
    ) -> ToolResult:
        if TRACER is None:
            return self._execute(name, arguments, context, allowed)
        with TRACER.start_as_current_span(f"tool.{name}") as span:
            span.set_attribute("datapilot.tool.name", name)
            span.set_attribute("datapilot.session_id", context.session_id)
            item = self._tools.get(name)
            if item is not None:
                span.set_attribute("datapilot.tool.stage", item.stage)
            result = self._execute(name, arguments, context, allowed)
            span.set_attribute("datapilot.tool.trace_id", result.trace_id)
            span.set_attribute("datapilot.tool.ok", result.ok)
            if result.error is not None:
                span.set_attribute("datapilot.tool.error_code", result.error.code.value)
            return result

    def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        allowed: set[str] | None = None,
    ) -> ToolResult:
        trace_id = f"tool_{uuid.uuid4().hex[:12]}"
        if allowed is not None and name not in allowed:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ErrorCode.POLICY_BLOCKED,
                    message=f"tool is not allowed in the current stage: {name}",
                ),
                trace_id=trace_id,
            )
        item = self._tools.get(name)
        if item is None:
            return ToolResult(
                ok=False,
                error=ToolError(code=ErrorCode.NOT_FOUND, message=f"unknown tool: {name}"),
                trace_id=trace_id,
            )
        try:
            args = item.args_model.model_validate(arguments)
            return item.handler(args=args, context=context, trace_id=trace_id)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ErrorCode.BAD_PARAMS,
                    message="tool arguments failed validation",
                    details={"errors": exc.errors(include_url=False)},
                ),
                trace_id=trace_id,
            )
        except Exception as exc:  # Tool boundary must normalize implementation failures.
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ErrorCode.INTERNAL,
                    message=f"tool execution failed: {type(exc).__name__}",
                ),
                trace_id=trace_id,
            )


def tool(
    *, name: str, description: str, args_model: type[BaseModel], stage: str
) -> Callable[[Callable[..., ToolResult]], Tool]:
    def decorator(handler: Callable[..., ToolResult]) -> Tool:
        parameters = inspect.signature(handler).parameters
        if set(parameters) != {"args", "context", "trace_id"}:
            raise TypeError("tool handler parameters must be args, context, trace_id")
        return Tool(
            name=name,
            description=description,
            args_model=args_model,
            handler=handler,
            stage=stage,
        )

    return decorator
