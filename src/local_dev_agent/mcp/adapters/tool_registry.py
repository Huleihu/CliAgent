"""将已校验的 MCP 工具适配到本地 ToolRegistry 的基础设施适配器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import RLock

from local_dev_agent.mcp.errors import McpConnectionError, McpToolCallError
from local_dev_agent.mcp.ports import McpCallContext, McpCallResult, McpClient
from local_dev_agent.mcp.schema import (
    McpServerConfiguration,
    McpToolAnnotations,
    McpToolDefinition,
    build_mcp_tool_name,
    validate_unique_mcp_tool_names,
)
from local_dev_agent.tools import Tool, ToolDefinition, ToolExecutionContext, ToolRegistry
from local_dev_agent.tools.errors import ToolAlreadyExistsError, ToolExecutionError


class McpToolAdapter(Tool):
    """把一个外部 MCP 工具伪装为本地可执行 Tool，而不泄漏传输细节。"""

    def __init__(
        self,
        *,
        server: McpServerConfiguration,
        client: McpClient,
        external_tool: McpToolDefinition,
    ) -> None:
        self._client = client
        self._server_name = server.name
        self._external_tool_name = external_tool.name
        self._definition = ToolDefinition(
            name=build_mcp_tool_name(server.name, external_tool.name),
            description=(
                f"MCP 服务“{server.name}”提供的工具：{external_tool.description}。"
                f"风险提示：{_format_annotations(external_tool.annotations)}"
            ),
            parameters=external_tool.input_schema,
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
        mcp_context = _to_mcp_context(context)
        try:
            result = self._client.call_tool(
                self._external_tool_name,
                arguments,
                context=mcp_context,
            )
        except McpToolCallError:
            raise
        except Exception as error:
            raise McpToolCallError(
                f"调用 MCP Server “{self._server_name}”的工具“{self._external_tool_name}”失败：{error}"
            ) from error
        if not isinstance(result, McpCallResult):
            raise McpToolCallError(
                f"MCP Server “{self._server_name}”的 tools/call 返回了无效结果。"
            )
        return {
            "content": [dict(item) for item in result.content],
            "structured_content": (
                dict(result.structured_content) if result.structured_content is not None else None
            ),
            "is_error": result.is_error,
            "diagnostic": (
                f"MCP 工具“{self._definition.name}”报告执行失败。"
                if result.is_error
                else "MCP 工具调用成功。"
            ),
        }


class ToolRegistryMcpToolPool:
    """以 ToolRegistry 的批量注册能力实现 MCP 工具池端口。"""

    def __init__(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry 必须是 ToolRegistry。")
        self._registry = registry
        self._tools_by_public_name: dict[str, McpToolDefinition] = {}
        self._lock = RLock()

    def register(
        self,
        *,
        server: McpServerConfiguration,
        client: McpClient,
        tools: Sequence[McpToolDefinition],
    ) -> tuple[str, ...]:
        public_names = validate_unique_mcp_tool_names(server.name, tools)
        adapters = tuple(
            McpToolAdapter(server=server, client=client, external_tool=tool) for tool in tools
        )
        try:
            self._registry.register_many(adapters)
        except ToolAlreadyExistsError as error:
            raise McpConnectionError(
                f"MCP Server “{server.name}”的工具名称与现有工具冲突：{error}"
            ) from error
        with self._lock:
            self._tools_by_public_name.update(
                {
                    adapter.definition.name: tool
                    for adapter, tool in zip(adapters, tools, strict=True)
                }
            )
        return public_names

    def get_annotations(self, public_tool_name: str) -> McpToolAnnotations | None:
        """返回已注册外部工具的风险提示；注册竞争窗口按未知工具处理。"""

        with self._lock:
            tool = self._tools_by_public_name.get(public_tool_name)
        return tool.annotations if tool is not None else None


def _to_mcp_context(context: ToolExecutionContext | None) -> McpCallContext:
    if context is None or context.call_id is None:
        raise ToolExecutionError("MCP 工具必须在携带 call_id 的执行上下文中调用。")
    return McpCallContext(
        session_id=context.session_id,
        run_id=context.run_id,
        step_id=context.step_id,
        call_id=context.call_id,
    )


def _format_annotations(annotations: McpToolAnnotations) -> str:
    """将已校验但并非权限证明的 annotations 显式暴露给模型。"""

    parts = ["声明只读" if annotations.read_only_hint else "未声明只读"]
    parts.append("可能有破坏性影响" if annotations.destructive_hint else "未声明破坏性影响")
    parts.append("可能访问外部系统" if annotations.open_world_hint else "不访问外部系统")
    return "；".join(parts) + "。"
