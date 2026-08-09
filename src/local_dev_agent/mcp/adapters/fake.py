"""用于教学与单元测试的内存 MCP Server 适配器。"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from local_dev_agent.mcp.errors import McpConnectionError, McpToolCallError
from local_dev_agent.mcp.ports import (
    McpCallContext,
    McpCallResult,
    McpClient,
)
from local_dev_agent.mcp.schema import McpServerConfiguration, McpToolDefinition

McpToolHandler = Callable[[Mapping[str, object], McpCallContext], McpCallResult]


@dataclass(frozen=True)
class FakeMcpCall:
    """记录 fake Server 收到的调用，便于断言关联上下文没有丢失。"""

    name: str
    arguments: Mapping[str, object]
    context: McpCallContext


class FakeMcpClient:
    """不访问网络的 MCP Client；它模拟 tools/list、tools/call 与关闭边界。"""

    def __init__(
        self,
        tools: Sequence[McpToolDefinition],
        handlers: Mapping[str, McpToolHandler],
    ) -> None:
        self._tools = tuple(tools)
        self._handlers = dict(handlers)
        self.list_contexts: list[McpCallContext | None] = []
        self.calls: list[FakeMcpCall] = []
        self.closed = False

    def list_tools(self, *, context: McpCallContext | None = None) -> Sequence[McpToolDefinition]:
        self._ensure_open()
        self.list_contexts.append(context)
        return self._tools

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        context: McpCallContext,
    ) -> McpCallResult:
        self._ensure_open()
        handler = self._handlers.get(name)
        if handler is None:
            raise McpToolCallError(f"Fake MCP Server 不存在工具：{name}。")
        copied_arguments = copy.deepcopy(dict(arguments))
        self.calls.append(FakeMcpCall(name=name, arguments=copied_arguments, context=context))
        return handler(copied_arguments, context)

    def close(self) -> None:
        self.closed = True

    def _ensure_open(self) -> None:
        if self.closed:
            raise McpConnectionError("Fake MCP Server 连接已经关闭。")


class FakeMcpClientConnector:
    """按配置名提供预置 fake Client 的连接器。"""

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self._clients = dict(clients)
        self.connection_contexts: list[tuple[str, McpCallContext | None]] = []

    def connect(
        self, server: McpServerConfiguration, *, context: McpCallContext | None = None
    ) -> McpClient:
        self.connection_contexts.append((server.name, context))
        client = self._clients.get(server.name)
        if client is None:
            raise McpConnectionError(f"没有为 MCP Server {server.name} 配置 fake 连接。")
        return client


class InMemoryMcpServerCatalog:
    """用于组合根与测试的只读配置目录。"""

    def __init__(self, servers: Sequence[McpServerConfiguration]) -> None:
        self._servers = {server.name: server for server in servers}
        if len(self._servers) != len(servers):
            raise McpConnectionError("MCP Server 配置名称不能重复。")

    def get(self, name: str) -> McpServerConfiguration | None:
        return self._servers.get(name)
