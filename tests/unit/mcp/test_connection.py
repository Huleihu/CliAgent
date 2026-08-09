from __future__ import annotations

import unittest

from local_dev_agent.mcp.adapters.fake import (
    FakeMcpClient,
    FakeMcpClientConnector,
    InMemoryMcpServerCatalog,
)
from local_dev_agent.mcp.adapters.tool_registry import ToolRegistryMcpToolPool
from local_dev_agent.mcp.errors import McpConnectionError
from local_dev_agent.mcp.ports import McpCallContext, McpCallResult
from local_dev_agent.mcp.schema import McpServerConfiguration, McpToolDefinition
from local_dev_agent.mcp.service import McpConnectionService
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry


class McpConnectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = McpCallContext(
            session_id="session-1", run_id="run-1", step_id="step-1", call_id="call-1"
        )
        self.server = McpServerConfiguration("docs")
        self.search = McpToolDefinition(
            "search",
            "搜索项目文档",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )

    def test_连接发现并原子注册工具且重复连接幂等(self) -> None:
        client = FakeMcpClient(
            [self.search],
            {"search": lambda _arguments, _context: McpCallResult(content=({"type": "text", "text": "S19"},))},
        )
        registry = ToolRegistry()
        service = self._service(client=client, registry=registry)

        first = service.connect("docs", context=self.context)
        second = service.connect("docs", context=self.context)

        self.assertEqual(first.connection.tool_names, ("mcp__docs__search",))
        self.assertFalse(first.already_connected)
        self.assertTrue(second.already_connected)
        self.assertEqual(client.list_contexts, [self.context])
        self.assertEqual(
            [definition.name for definition in registry.list_definitions()],
            ["mcp__docs__search"],
        )

    def test_注册冲突会关闭连接且不留下半注册工具(self) -> None:
        preview = McpToolDefinition("preview", "预览项目文档", {"type": "object"})
        client = FakeMcpClient([self.search, preview], {})
        registry = ToolRegistry()
        registry.register(
            FakeTool(
                definition=ToolDefinition(
                    name="mcp__docs__preview",
                    description="既有工具",
                    parameters={"type": "object", "properties": {}},
                ),
                result={},
            )
        )
        service = self._service(client=client, registry=registry)

        with self.assertRaisesRegex(McpConnectionError, "名称与现有工具冲突"):
            service.connect("docs", context=self.context)

        self.assertTrue(client.closed)
        self.assertEqual(
            [definition.name for definition in registry.list_definitions()],
            ["mcp__docs__preview"],
        )

    def test_未配置服务不会尝试连接(self) -> None:
        client = FakeMcpClient([self.search], {})
        registry = ToolRegistry()
        service = self._service(client=client, registry=registry)

        with self.assertRaisesRegex(McpConnectionError, "未配置"):
            service.connect("jira", context=self.context)

        self.assertEqual(client.list_contexts, [])
        self.assertEqual(registry.list_definitions(), ())

    def _service(self, *, client: FakeMcpClient, registry: ToolRegistry) -> McpConnectionService:
        return McpConnectionService(
            server_catalog=InMemoryMcpServerCatalog([self.server]),
            connector=FakeMcpClientConnector({"docs": client}),
            tool_pool=ToolRegistryMcpToolPool(registry),
        )
