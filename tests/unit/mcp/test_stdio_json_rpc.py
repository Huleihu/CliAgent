from __future__ import annotations

import sys
import unittest
from pathlib import Path

from local_dev_agent.mcp.adapters.stdio_json_rpc import (
    StdioMcpClientConnector,
    StdioMcpLaunchConfiguration,
)
from local_dev_agent.mcp.errors import McpProtocolError
from local_dev_agent.mcp.ports import McpCallContext
from local_dev_agent.mcp.schema import McpServerConfiguration


class StdioMcpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = McpCallContext(
            session_id="session-1", run_id="run-1", step_id="step-1", call_id="call-1"
        )
        self.server = McpServerConfiguration("docs")
        self.configuration = StdioMcpLaunchConfiguration(
            server_name="docs",
            command=sys.executable,
            arguments=(str(Path(__file__).with_name("stdio_server.py")),),
            cwd=Path(__file__).parent.resolve(),
        )

    def test_stdio_connector完成初始化发现并调用真实子进程(self) -> None:
        client = StdioMcpClientConnector([self.configuration]).connect(
            self.server,
            context=self.context,
        )
        try:
            tools = tuple(client.list_tools(context=self.context))
            result = client.call_tool("search", {"query": "S19"}, context=self.context)
        finally:
            client.close()

        self.assertEqual(tools[0].name, "search")
        self.assertTrue(tools[0].annotations.read_only_hint)
        self.assertEqual(result.content[0]["text"], "找到测试文档")
        received_meta = result.structured_content["received_meta"]
        self.assertEqual(received_meta["io.local-dev-agent/context"]["run_id"], "run-1")
        self.assertEqual(received_meta["io.local-dev-agent/context"]["call_id"], "call-1")

    def test_stdio_connector把json_rpc错误转换为中文可诊断异常(self) -> None:
        client = StdioMcpClientConnector([self.configuration]).connect(self.server)
        try:
            with self.assertRaisesRegex(McpProtocolError, "未知工具"):
                client.call_tool("missing", {}, context=self.context)
        finally:
            client.close()

    def test_stdio配置拒绝不存在的cwd与重复服务名(self) -> None:
        with self.assertRaisesRegex(ValueError, "存在的绝对目录"):
            StdioMcpLaunchConfiguration(
                server_name="docs",
                command=sys.executable,
                cwd=Path("missing").resolve(),
            )
        with self.assertRaisesRegex(ValueError, "必须是正数"):
            StdioMcpLaunchConfiguration(
                server_name="docs",
                command=sys.executable,
                request_timeout_seconds=0,
            )
        with self.assertRaisesRegex(ValueError, "不能重复"):
            StdioMcpClientConnector([self.configuration, self.configuration])
