from __future__ import annotations

import json
import threading
import unittest
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from local_dev_agent.mcp.adapters.streamable_http import (
    StreamableHttpMcpClientConnector,
    StreamableHttpMcpConfiguration,
)
from local_dev_agent.mcp.errors import McpConnectionError
from local_dev_agent.mcp.ports import McpCallContext
from local_dev_agent.mcp.schema import McpServerConfiguration


class _McpHttpHandler(BaseHTTPRequestHandler):
    """仅供传输适配器测试使用的本地 Streamable HTTP MCP Server。"""

    requests: ClassVar[list[tuple[str, dict[str, str], Mapping[str, object] | None]]] = []

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        message = json.loads(body.decode("utf-8"))
        self.requests.append(("POST", dict(self.headers.items()), message))
        method = message["method"]
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            self._write_json(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
                },
                session_id="http-session-1",
            )
            return
        if method == "tools/list":
            self._write_json(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "search",
                                "description": "搜索测试文档。",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"query": {"type": "string"}},
                                    "required": ["query"],
                                },
                                "annotations": {"readOnlyHint": True},
                            }
                        ]
                    },
                }
            )
            return
        if method == "tools/call" and message["params"]["arguments"].get("query") == "forbidden":
            self.send_response(401)
            self.end_headers()
            return
        if method == "tools/call":
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "content": [{"type": "text", "text": "找到 HTTP 测试文档。"}],
                    "structuredContent": {"received_meta": message["params"].get("_meta")},
                },
            }
            self._write_sse(response)
            return
        self.send_response(500)
        self.end_headers()

    def do_DELETE(self) -> None:  # noqa: N802
        self.requests.append(("DELETE", dict(self.headers.items()), None))
        self.send_response(204)
        self.end_headers()

    def _write_json(self, message: Mapping[str, object], *, session_id: str | None = None) -> None:
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if session_id is not None:
            self.send_header("MCP-Session-Id", session_id)
        self.end_headers()
        self.wfile.write(payload)

    def _write_sse(self, message: Mapping[str, object]) -> None:
        payload = f"event: message\ndata: {json.dumps(message, ensure_ascii=False)}\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """测试中不向终端输出 HTTP 访问日志。"""


class StreamableHttpMcpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _McpHttpHandler.requests = []
        self._http_server = ThreadingHTTPServer(("127.0.0.1", 0), _McpHttpHandler)
        self._thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        self._thread.start()
        self.context = McpCallContext(
            session_id="session-1", run_id="run-1", step_id="step-1", call_id="call-1"
        )
        self.server = McpServerConfiguration("docs")
        self.configuration = StreamableHttpMcpConfiguration(
            server_name="docs",
            endpoint_url=f"http://127.0.0.1:{self._http_server.server_port}/mcp",
            bearer_token="test-token",
        )

    def tearDown(self) -> None:
        self._http_server.shutdown()
        self._http_server.server_close()
        self._thread.join()

    def test_http_connector完成初始化发现调用并关闭会话(self) -> None:
        client = StreamableHttpMcpClientConnector([self.configuration]).connect(
            self.server, context=self.context
        )
        try:
            tools = tuple(client.list_tools(context=self.context))
            result = client.call_tool("search", {"query": "S19"}, context=self.context)
        finally:
            client.close()

        self.assertEqual(tools[0].name, "search")
        self.assertTrue(tools[0].annotations.read_only_hint)
        self.assertEqual(result.content[0]["text"], "找到 HTTP 测试文档。")
        self.assertEqual(
            result.structured_content["received_meta"]["io.local-dev-agent/context"]["run_id"],
            "run-1",
        )
        posts = [request for request in _McpHttpHandler.requests if request[0] == "POST"]
        self.assertNotIn("Mcp-Protocol-Version", posts[0][1])
        self.assertEqual(posts[0][1]["Authorization"], "Bearer test-token")
        self.assertEqual(posts[1][1]["Mcp-Protocol-Version"], "2025-11-25")
        self.assertEqual(posts[1][1]["Mcp-Session-Id"], "http-session-1")
        delete_request = _McpHttpHandler.requests[-1]
        self.assertEqual(delete_request[0], "DELETE")
        self.assertEqual(delete_request[1]["Mcp-Session-Id"], "http-session-1")

    def test_http_connector将认证失败转换为可诊断中文异常(self) -> None:
        client = StreamableHttpMcpClientConnector([self.configuration]).connect(self.server)
        try:
            with self.assertRaisesRegex(McpConnectionError, "HTTP 401"):
                client.call_tool("search", {"query": "forbidden"}, context=self.context)
        finally:
            client.close()

    def test_http配置拒绝远程明文地址和重复服务名(self) -> None:
        with self.assertRaisesRegex(ValueError, "远程 Server 必须使用 https"):
            StreamableHttpMcpConfiguration(
                server_name="docs", endpoint_url="http://example.com/mcp"
            )
        with self.assertRaisesRegex(ValueError, "不能重复"):
            StreamableHttpMcpClientConnector([self.configuration, self.configuration])
