"""通过 stdio MCP 服务调用工具注册表中的白名单工具。"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from datapilot_verify.app import build_registry
from datapilot_verify.tools.base import ToolContext, ToolRegistry

DEFAULT_EXPOSED: frozenset[str] = frozenset(
    {
        "inspect_dataset",
        "resolve_metric",
        "search_metric_docs",
        "run_analysis",
        "get_evidence",
        "make_chart",
    }
)

SERVER_NAME = "datapilot-verify"
SERVER_INSTRUCTIONS = (
    "DataPilot Verify 经营分析工具。所有数据事实、指标口径与计算结果都必须通过这些工具"
    "获取，不要自行编造数值。返回结果中带有 evidence 与 trace_id，用于审计与复核。"
)


class DataPilotMCPServer:
    def __init__(
        self,
        project_root: Path,
        workspace: Path,
        output_dir: Path,
        exposed: frozenset[str] = DEFAULT_EXPOSED,
    ):
        self.allowed = set(exposed)
        self.registry: ToolRegistry = build_registry(project_root)
        self.context = ToolContext(
            session_id=f"mcp_{uuid.uuid4().hex[:12]}",
            workspace=workspace,
            output_dir=output_dir,
        )
        self.server = Server(
            name=SERVER_NAME,
            instructions=SERVER_INSTRUCTIONS,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    async def _list_tools(
        self, _ctx: ServerRequestContext, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=schema["name"],
                    description=schema["description"],
                    input_schema=schema["parameters"],
                )
                for schema in self._tool_schemas()
            ]
        )

    async def _call_tool(
        self, _ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        result = await asyncio.to_thread(
            self.registry.execute,
            params.name,
            params.arguments or {},
            self.context,
            allowed=self.allowed,
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.model_dump_json())],
            is_error=not result.ok,
        )

    @property
    def tool_names(self) -> list[str]:
        return [schema["name"] for schema in self._tool_schemas()]

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [schema["function"] for schema in self.registry.schemas(allowed=self.allowed)]

    async def run(self) -> None:
        async with stdio_server() as (read_stream, write_stream):
            options = self.server.create_initialization_options()
            await self.server.run(read_stream, write_stream, options)


def main() -> int:
    ap = argparse.ArgumentParser(description="DataPilot Verify MCP server（stdio）")
    ap.add_argument("--project-root", default=None, help="项目根目录（默认当前目录）")
    ap.add_argument("--workspace", default="workspace", help="数据工作区目录")
    ap.add_argument("--output-dir", default="artifacts/mcp", help="产物输出目录")
    ap.add_argument(
        "--expose",
        nargs="*",
        default=None,
        help="通过 MCP 暴露的工具名（缺省用内置白名单；单独传 --expose 则不暴露工具）",
    )
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd().resolve()
    workspace = (project_root / args.workspace).resolve()
    output_dir = (project_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    exposed = DEFAULT_EXPOSED if args.expose is None else frozenset(args.expose or [])
    server = DataPilotMCPServer(project_root, workspace, output_dir, exposed=exposed)

    print(
        f"[{SERVER_NAME}] 已启动：暴露 {len(server.tool_names)} 个工具 "
        f"{server.tool_names}，workspace={workspace}",
        file=sys.stderr,
        flush=True,
    )
    asyncio.run(server.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
