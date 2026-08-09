"""协调连接、工具发现和本地工具池注册的 MCP 应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from local_dev_agent.mcp.errors import McpConnectionError, McpProtocolError, McpToolDefinitionError
from local_dev_agent.mcp.ports import (
    McpCallContext,
    McpClient,
    McpClientConnector,
    McpServerCatalog,
    McpToolPool,
)
from local_dev_agent.mcp.schema import McpToolDefinition, validate_unique_mcp_tool_names


@dataclass(frozen=True)
class McpConnection:
    """一次成功连接并注册完成后保留的进程内事实。"""

    server_name: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True)
class McpConnectResult:
    """供 connect_mcp 工具回填给模型的连接结果。"""

    connection: McpConnection
    already_connected: bool


class McpConnectionService:
    """仅连接显式配置的 Server，并以全成或全不成方式暴露其工具。"""

    def __init__(
        self,
        *,
        server_catalog: McpServerCatalog,
        connector: McpClientConnector,
        tool_pool: McpToolPool,
    ) -> None:
        self._server_catalog = server_catalog
        self._connector = connector
        self._tool_pool = tool_pool
        self._connections: dict[str, McpConnection] = {}
        # 同一服务的连接、发现与注册必须串行，避免并发请求重复注册工具。
        self._lock = RLock()

    def connect(self, server_name: str, *, context: McpCallContext) -> McpConnectResult:
        """连接一次 Server；重复连接返回已有事实而不会再次发现或注册。"""

        if not isinstance(server_name, str) or not server_name.strip():
            raise McpConnectionError("MCP Server 名称必须是非空字符串。")
        server = self._server_catalog.get(server_name)
        if server is None:
            raise McpConnectionError(f"未配置名为“{server_name}”的 MCP Server。")

        with self._lock:
            existing = self._connections.get(server.normalized_name)
            if existing is not None:
                return McpConnectResult(connection=existing, already_connected=True)

            client = self._connect(server_name=server.name, context=context)
            try:
                tools = self._list_and_validate_tools(client=client, server_name=server.name, context=context)
                public_names = self._tool_pool.register(server=server, client=client, tools=tools)
            except Exception as error:
                self._close_after_failure(client=client)
                if isinstance(error, McpConnectionError):
                    raise
                if isinstance(error, McpToolDefinitionError):
                    raise McpConnectionError(
                        f"MCP Server “{server.name}”返回了无效工具定义：{error}"
                    ) from error
                raise McpConnectionError(
                    f"连接 MCP Server “{server.name}”后注册工具失败，内置工具池未被修改：{error}"
                ) from error

            connection = McpConnection(server_name=server.name, tool_names=public_names)
            self._connections[server.normalized_name] = connection
            return McpConnectResult(connection=connection, already_connected=False)

    def _connect(self, *, server_name: str, context: McpCallContext) -> McpClient:
        server = self._server_catalog.get(server_name)
        if server is None:
            raise AssertionError("已验证的 MCP Server 配置不应消失。")
        try:
            return self._connector.connect(server, context=context)
        except McpProtocolError:
            raise
        except Exception as error:
            raise McpConnectionError(f"连接 MCP Server “{server_name}”失败：{error}") from error

    @staticmethod
    def _list_and_validate_tools(
        *, client: McpClient, server_name: str, context: McpCallContext
    ) -> tuple[McpToolDefinition, ...]:
        try:
            tools = tuple(client.list_tools(context=context))
        except McpProtocolError:
            raise
        except Exception as error:
            raise McpConnectionError(
                f"读取 MCP Server “{server_name}”的 tools/list 失败：{error}"
            ) from error
        if not all(isinstance(tool, McpToolDefinition) for tool in tools):
            raise McpToolDefinitionError(
                "MCP Server 的 tools/list 必须返回已校验的工具定义对象。"
            )
        validate_unique_mcp_tool_names(server_name, tools)
        return tools

    @staticmethod
    def _close_after_failure(*, client: McpClient) -> None:
        try:
            client.close()
        except Exception:
            # 原始连接、发现或注册错误更有诊断价值，关闭失败不应掩盖它。
            pass
