from __future__ import annotations

import unittest

from local_dev_agent.mcp.adapters.fake import (
    FakeMcpClient,
    FakeMcpClientConnector,
    InMemoryMcpServerCatalog,
)
from local_dev_agent.mcp.errors import McpConnectionError, McpToolCallError
from local_dev_agent.mcp.ports import McpCallContext, McpCallResult
from local_dev_agent.mcp.schema import McpServerConfiguration, McpToolDefinition


class FakeMcpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = McpCallContext(
            session_id="session-1", run_id="run-1", step_id="step-1", call_id="call-1"
        )
        self.tool = McpToolDefinition(
            "search",
            "搜索项目文档",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )

    def test_fake_client_记录列表与调用的完整关联上下文(self) -> None:
        received: list[tuple[dict[str, object], McpCallContext]] = []

        def search(arguments: object, context: McpCallContext) -> McpCallResult:
            received.append((dict(arguments), context))
            return McpCallResult(content=({"type": "text", "text": "找到 S19 文档"},))

        client = FakeMcpClient([self.tool], {"search": search})
        self.assertEqual(tuple(client.list_tools(context=self.context)), (self.tool,))
        result = client.call_tool("search", {"query": "S19"}, context=self.context)

        self.assertFalse(result.is_error)
        self.assertEqual(client.list_contexts, [self.context])
        self.assertEqual(client.calls[0].context, self.context)
        self.assertEqual(received, [({"query": "S19"}, self.context)])

    def test_fake_client_在未知工具或关闭后给出可诊断错误(self) -> None:
        client = FakeMcpClient([self.tool], {})

        with self.assertRaisesRegex(McpToolCallError, "不存在工具"):
            client.call_tool("missing", {}, context=self.context)
        client.close()
        with self.assertRaisesRegex(McpConnectionError, "已经关闭"):
            client.list_tools()

    def test_fake_connector与内存目录只解析显式配置(self) -> None:
        server = McpServerConfiguration("docs")
        client = FakeMcpClient([self.tool], {"search": lambda _arguments, _context: McpCallResult(content=({"type": "text", "text": "ok"},))})
        catalog = InMemoryMcpServerCatalog([server])
        connector = FakeMcpClientConnector({"docs": client})

        self.assertIs(catalog.get("docs"), server)
        self.assertIsNone(catalog.get("unknown"))
        self.assertIs(connector.connect(server, context=self.context), client)
        self.assertEqual(connector.connection_contexts, [("docs", self.context)])
        with self.assertRaisesRegex(McpConnectionError, "没有为"):
            connector.connect(McpServerConfiguration("jira"))
