"""供 stdio JSON-RPC 适配器测试启动的最小 MCP Server。"""

from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def _send(message: dict[str, object]) -> None:
    print(json.dumps(message, ensure_ascii=False), flush=True)


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
            }
        )
    elif method == "tools/list":
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "search",
                            "description": "搜索测试文档",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                            "annotations": {"readOnlyHint": True, "openWorldHint": False},
                        }
                    ]
                },
            }
        )
    elif method == "tools/call":
        parameters = request.get("params", {})
        if parameters.get("name") != "search":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "未知工具"},
                }
            )
            continue
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": "找到测试文档"}],
                    "structuredContent": {"received_meta": parameters.get("_meta")},
                },
            }
        )
