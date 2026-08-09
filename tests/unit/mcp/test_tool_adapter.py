from __future__ import annotations

import unittest

from local_dev_agent.mcp.adapters.fake import FakeMcpClient, FakeMcpClientConnector, InMemoryMcpServerCatalog
from local_dev_agent.mcp.adapters.tool_registry import ToolRegistryMcpToolPool
from local_dev_agent.mcp.ports import McpCallResult
from local_dev_agent.mcp.schema import McpServerConfiguration, McpToolDefinition
from local_dev_agent.mcp.service import McpConnectionService
from local_dev_agent.tools import ToolCallRequest, ToolExecutionContext, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import ConnectMcpTool


class McpToolAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ToolExecutionContext(
            session_id="session-1", run_id="run-1", step_id="step-1", call_id="call-1"
        )
        self.search = McpToolDefinition(
            "search",
            "搜索项目文档",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )

    def test_connect_mcp后外部工具保留调用关联信息(self) -> None:
        received_contexts = []

        def search(_arguments: object, context: object) -> McpCallResult:
            received_contexts.append(context)
            return McpCallResult(
                content=({"type": "text", "text": "S19 协议文档"},),
                structured_content={"count": 1},
            )

        registry, client = self._connected_registry({"search": search})
        executor = ToolExecutor(registry)
        connect_result = executor.execute(
            ToolCallRequest(name="connect_mcp", arguments={"name": "docs"}, call_id="call-1"),
            context=self.context,
        )
        search_result = executor.execute(
            ToolCallRequest(
                name="mcp__docs__search", arguments={"query": "S19"}, call_id="call-1"
            ),
            context=self.context,
        )

        self.assertTrue(connect_result.success)
        self.assertEqual(connect_result.data["tools"], ["mcp__docs__search"])
        self.assertTrue(search_result.success)
        self.assertEqual(search_result.data["structured_content"], {"count": 1})
        self.assertEqual(client.calls[0].context.session_id, "session-1")
        self.assertEqual(client.calls[0].context.run_id, "run-1")
        self.assertEqual(client.calls[0].context.call_id, "call-1")
        self.assertEqual(received_contexts, [client.calls[0].context])

    def test_mcp错误结果仍以中文诊断回填模型(self) -> None:
        registry, _client = self._connected_registry(
            {
                "search": lambda _arguments, _context: McpCallResult(
                    content=({"type": "text", "text": "索引暂不可用"},), is_error=True
                )
            }
        )
        executor = ToolExecutor(registry)
        executor.execute(
            ToolCallRequest(name="connect_mcp", arguments={"name": "docs"}, call_id="call-1"),
            context=self.context,
        )

        result = executor.execute(
            ToolCallRequest(
                name="mcp__docs__search", arguments={"query": "S19"}, call_id="call-1"
            ),
            context=self.context,
        )

        self.assertTrue(result.success)
        self.assertTrue(result.data["is_error"])
        self.assertIn("报告执行失败", result.data["diagnostic"])

    def test_mcp工具缺少call_id会被本地边界拒绝(self) -> None:
        registry, _client = self._connected_registry(
            {"search": lambda _arguments, _context: McpCallResult(content=({"type": "text", "text": "ok"},))}
        )
        executor = ToolExecutor(registry)
        executor.execute(
            ToolCallRequest(name="connect_mcp", arguments={"name": "docs"}, call_id="call-1"),
            context=self.context,
        )
        context_without_call_id = ToolExecutionContext(
            session_id="session-1", run_id="run-1", step_id="step-2", call_id=None
        )

        result = executor.execute(
            ToolCallRequest(name="mcp__docs__search", arguments={"query": "S19"}),
            context=context_without_call_id,
        )

        self.assertFalse(result.success)
        self.assertIn("携带 call_id", result.error["message"])

    def _connected_registry(self, handlers: object) -> tuple[ToolRegistry, FakeMcpClient]:
        server = McpServerConfiguration("docs")
        client = FakeMcpClient([self.search], handlers)
        registry = ToolRegistry()
        service = McpConnectionService(
            server_catalog=InMemoryMcpServerCatalog([server]),
            connector=FakeMcpClientConnector({"docs": client}),
            tool_pool=ToolRegistryMcpToolPool(registry),
        )
        registry.register(ConnectMcpTool(service))
        return registry, client
