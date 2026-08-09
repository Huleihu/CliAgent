"""Lead 用于连接已配置 MCP Server 的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.mcp import McpCallContext
from local_dev_agent.mcp.service import McpConnectionService

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


class ConnectMcpTool(Tool):
    """连接一个已配置 MCP Server，并将其发现的工具加入当前工具池。"""

    def __init__(self, service: McpConnectionService) -> None:
        if not isinstance(service, McpConnectionService):
            raise TypeError("service 必须是 McpConnectionService。")
        self._service = service
        self._definition = ToolDefinition(
            name="connect_mcp",
            description="连接一个已配置的 MCP Server，并发现其可用工具。",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            tags=("mcp",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolValidationError("字段“name”必须是非空字符串。")
        result = self._service.connect(name, context=_to_mcp_context(context))
        return {
            "server_name": result.connection.server_name,
            "tools": list(result.connection.tool_names),
            "already_connected": result.already_connected,
        }


def _to_mcp_context(context: ToolExecutionContext | None) -> McpCallContext:
    if context is None or context.call_id is None:
        raise ToolExecutionError("connect_mcp 必须在携带 call_id 的执行上下文中调用。")
    return McpCallContext(
        session_id=context.session_id,
        run_id=context.run_id,
        step_id=context.step_id,
        call_id=context.call_id,
    )
