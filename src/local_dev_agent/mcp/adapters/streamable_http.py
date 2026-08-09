"""通过显式配置的 Streamable HTTP 端点调用 MCP Server。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from local_dev_agent.mcp.errors import McpConnectionError, McpProtocolError, McpToolCallError
from local_dev_agent.mcp.ports import McpCallContext, McpCallResult, McpClient
from local_dev_agent.mcp.schema import (
    McpServerConfiguration,
    McpToolAnnotations,
    McpToolDefinition,
)

_JSON_RPC_VERSION = "2.0"
_SUPPORTED_PROTOCOL_VERSION = "2025-11-25"
_CONTEXT_META_KEY = "io.local-dev-agent/context"
_SESSION_HEADER = "MCP-Session-Id"
_PROTOCOL_HEADER = "MCP-Protocol-Version"


@dataclass(frozen=True)
class StreamableHttpMcpConfiguration:
    """一个显式配置的 Streamable HTTP MCP Server，不进行网络发现。"""

    server_name: str
    endpoint_url: str
    bearer_token: str | None = None
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.server_name, str) or not self.server_name.strip():
            raise ValueError("HTTP MCP 配置的 server_name 必须是非空字符串。")
        _validate_endpoint_url(self.endpoint_url)
        if self.bearer_token is not None:
            if (
                not isinstance(self.bearer_token, str)
                or not self.bearer_token
                or any(character.isspace() for character in self.bearer_token)
                or any(ord(character) < 32 or ord(character) == 127 for character in self.bearer_token)
            ):
                raise ValueError("HTTP MCP 配置的 bearer_token 必须是无空白和控制字符的非空字符串。")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("HTTP MCP 配置的 request_timeout_seconds 必须是正数。")


class StreamableHttpMcpClientConnector:
    """按 Server 名创建已配置的 Streamable HTTP MCP 连接并完成初始化。"""

    def __init__(self, configurations: Sequence[StreamableHttpMcpConfiguration]) -> None:
        self._configurations = {configuration.server_name: configuration for configuration in configurations}
        if len(self._configurations) != len(configurations):
            raise ValueError("HTTP MCP 配置的 server_name 不能重复。")

    def connect(
        self, server: McpServerConfiguration, *, context: McpCallContext | None = None
    ) -> McpClient:
        configuration = self._configurations.get(server.name)
        if configuration is None:
            raise McpConnectionError(
                f"没有为 MCP Server ‘{server.name}’ 配置 Streamable HTTP 端点。"
            )
        client = StreamableHttpMcpClient(configuration)
        try:
            client.initialize(context=context)
        except Exception:
            client.close()
            raise
        return client


class StreamableHttpMcpClient:
    """每个连接持有一个 MCP 会话；不实现自动重连或旧版 HTTP+SSE 传输。"""

    def __init__(self, configuration: StreamableHttpMcpConfiguration) -> None:
        self._configuration = configuration
        self._next_request_id = 1
        self._protocol_version: str | None = None
        self._session_id: str | None = None
        self._initialized = False
        self._closed = False
        self._lock = RLock()

    def initialize(self, *, context: McpCallContext | None = None) -> None:
        """执行 initialize 与 initialized 通知，并保存 Server 分配的会话标识。"""

        with self._lock:
            self._ensure_open()
            if self._initialized:
                return
            result, session_id = self._request_locked(
                "initialize",
                {
                    "protocolVersion": _SUPPORTED_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "local-dev-agent", "version": "0.1.0"},
                    **_context_meta(context),
                },
            )
            protocol_version = result.get("protocolVersion")
            if not isinstance(protocol_version, str) or not protocol_version:
                raise McpProtocolError("MCP initialize 响应缺少有效的 protocolVersion。")
            self._protocol_version = protocol_version
            self._session_id = session_id
            self._notify_locked("notifications/initialized", {})
            self._initialized = True

    def list_tools(self, *, context: McpCallContext | None = None) -> Sequence[McpToolDefinition]:
        """执行可分页的 tools/list，并在本地校验外部工具定义。"""

        with self._lock:
            self._ensure_initialized()
            tools: list[McpToolDefinition] = []
            cursor: str | None = None
            seen_cursors: set[str] = set()
            while True:
                parameters: dict[str, object] = dict(_context_meta(context))
                if cursor is not None:
                    parameters["cursor"] = cursor
                result, _ = self._request_locked("tools/list", parameters)
                raw_tools = result.get("tools")
                if not isinstance(raw_tools, list):
                    raise McpProtocolError("MCP tools/list 响应的 tools 必须是数组。")
                tools.extend(_to_mcp_tool_definition(item) for item in raw_tools)
                next_cursor = result.get("nextCursor")
                if next_cursor is None:
                    return tuple(tools)
                if not isinstance(next_cursor, str) or not next_cursor:
                    raise McpProtocolError(
                        "MCP tools/list 响应的 nextCursor 必须是非空字符串或空值。"
                    )
                if next_cursor in seen_cursors:
                    raise McpProtocolError("MCP tools/list 响应出现重复 cursor，已停止发现。")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        context: McpCallContext,
    ) -> McpCallResult:
        """将本地工具调用映射为 tools/call，并传递 run 与调用关联信息。"""

        if not isinstance(name, str) or not name:
            raise McpToolCallError("MCP tools/call 的 name 必须是非空字符串。")
        if not isinstance(arguments, Mapping):
            raise McpToolCallError("MCP tools/call 的 arguments 必须是对象。")
        with self._lock:
            self._ensure_initialized()
            result, _ = self._request_locked(
                "tools/call",
                {"name": name, "arguments": dict(arguments), **_context_meta(context)},
            )
        content = result.get("content")
        if not isinstance(content, list) or not content or not all(
            isinstance(item, Mapping) for item in content
        ):
            raise McpProtocolError("MCP tools/call 响应的 content 必须是非空对象数组。")
        structured_content = result.get("structuredContent")
        if structured_content is not None and not isinstance(structured_content, Mapping):
            raise McpProtocolError("MCP tools/call 响应的 structuredContent 必须是对象或空值。")
        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            raise McpProtocolError("MCP tools/call 响应的 isError 必须是布尔值。")
        return McpCallResult(
            content=tuple(dict(item) for item in content),
            structured_content=(dict(structured_content) if structured_content is not None else None),
            is_error=is_error,
        )

    def close(self) -> None:
        """尽力删除服务端会话；关闭失败不覆盖此前业务调用的错误。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._session_id is None:
                return
            request = Request(
                self._configuration.endpoint_url,
                headers=self._headers(include_protocol_version=True),
                method="DELETE",
            )
            try:
                with urlopen(request, timeout=min(self._configuration.request_timeout_seconds, 5.0)):
                    pass
            except (HTTPError, URLError, OSError):
                # 会话只存在于当前进程内，关闭时不重试也不影响其他 Run。
                return

    def _ensure_initialized(self) -> None:
        self._ensure_open()
        if not self._initialized:
            raise McpConnectionError("MCP HTTP 连接尚未完成 initialize。")

    def _ensure_open(self) -> None:
        if self._closed:
            raise McpConnectionError("MCP HTTP 连接已经关闭。")

    def _request_locked(
        self, method: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], str | None]:
        request_id = self._next_request_id
        self._next_request_id += 1
        response, session_id = self._post_locked(
            {"jsonrpc": _JSON_RPC_VERSION, "id": request_id, "method": method, "params": parameters},
            method=method,
        )
        message = _select_json_rpc_response(
            response,
            request_id=request_id,
            method=method,
            server_name=self._configuration.server_name,
        )
        error = message.get("error")
        if error is not None:
            raise McpProtocolError(_format_json_rpc_error(error))
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise McpProtocolError(f"MCP {method} 响应缺少对象 result。")
        return result, session_id

    def _notify_locked(self, method: str, parameters: Mapping[str, object]) -> None:
        self._post_locked(
            {"jsonrpc": _JSON_RPC_VERSION, "method": method, "params": parameters}, method=method
        )

    def _post_locked(self, message: Mapping[str, object], *, method: str) -> tuple[object, str | None]:
        try:
            payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise McpProtocolError(f"无法编码发往 MCP Server 的 {method} JSON-RPC 消息：{error}") from error
        request = Request(
            self._configuration.endpoint_url,
            data=payload,
            headers=self._headers(include_protocol_version=self._protocol_version is not None),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._configuration.request_timeout_seconds) as response:
                session_id = _extract_session_id(response.headers.get(_SESSION_HEADER))
                status = response.status
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as error:
            raise McpConnectionError(
                f"MCP Server ‘{self._configuration.server_name}’ 的 HTTP 请求 {method} 被拒绝："
                f"HTTP {error.code}。"
            ) from error
        except (URLError, OSError) as error:
            raise McpConnectionError(
                f"连接 MCP Server ‘{self._configuration.server_name}’ 的 HTTP 端点失败：{error}"
            ) from error
        if "id" not in message:
            if status not in (200, 202):
                raise McpProtocolError(f"MCP 通知 {method} 返回了不支持的 HTTP 状态 {status}。")
            return {}, session_id
        if status != 200:
            raise McpProtocolError(f"MCP 请求 {method} 返回了不支持的 HTTP 状态 {status}。")
        return _decode_http_json_rpc_body(body, content_type, server_name=self._configuration.server_name), session_id

    def _headers(self, *, include_protocol_version: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self._configuration.bearer_token is not None:
            headers["Authorization"] = f"Bearer {self._configuration.bearer_token}"
        if self._session_id is not None:
            headers[_SESSION_HEADER] = self._session_id
        if include_protocol_version and self._protocol_version is not None:
            headers[_PROTOCOL_HEADER] = self._protocol_version
        return headers


def _validate_endpoint_url(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("HTTP MCP 配置的 endpoint_url 必须是非空字符串。")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("HTTP MCP 配置的 endpoint_url 必须是带主机名的 http 或 https URL。")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("HTTP MCP 配置的 endpoint_url 不能携带用户名、密码或片段。")
    if parsed.scheme == "http" and parsed.hostname.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("HTTP MCP 仅允许本地回环地址使用明文 http；远程 Server 必须使用 https。")


def _context_meta(context: McpCallContext | None) -> Mapping[str, object]:
    if context is None:
        return {}
    return {
        "_meta": {
            _CONTEXT_META_KEY: {
                "session_id": context.session_id,
                "run_id": context.run_id,
                "step_id": context.step_id,
                "call_id": context.call_id,
            }
        }
    }


def _extract_session_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise McpProtocolError("MCP Server 返回了无效的 MCP-Session-Id 响应头。")
    return value


def _decode_http_json_rpc_body(body: bytes, content_type: str, *, server_name: str) -> object:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise McpProtocolError(f"MCP Server ‘{server_name}’ 返回了非 UTF-8 的 HTTP 响应。") from error
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "application/json":
        return _parse_json_rpc_message(text, server_name=server_name)
    if media_type == "text/event-stream":
        return tuple(_parse_sse_messages(text, server_name=server_name))
    raise McpProtocolError(
        f"MCP Server ‘{server_name}’ 返回了不支持的 Content-Type：{content_type or '缺失'}。"
    )


def _parse_sse_messages(text: str, *, server_name: str) -> Sequence[Mapping[str, object]]:
    messages: list[Mapping[str, object]] = []
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            if data_lines:
                messages.append(_parse_json_rpc_message("\n".join(data_lines), server_name=server_name))
                data_lines.clear()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        messages.append(_parse_json_rpc_message("\n".join(data_lines), server_name=server_name))
    if not messages:
        raise McpProtocolError(f"MCP Server ‘{server_name}’ 返回的 SSE 响应不含 JSON-RPC 数据。")
    return tuple(messages)


def _select_json_rpc_response(
    response: object, *, request_id: int, method: str, server_name: str
) -> Mapping[str, object]:
    messages: Sequence[Mapping[str, object]]
    if isinstance(response, Mapping):
        messages = (response,)
    elif isinstance(response, tuple) and all(isinstance(item, Mapping) for item in response):
        messages = response
    else:
        raise McpProtocolError(f"MCP Server ‘{server_name}’ 返回了无效的 JSON-RPC 响应。")
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise McpProtocolError(f"MCP Server ‘{server_name}’ 没有返回请求 {method} 的匹配响应。")


def _parse_json_rpc_message(text: str, *, server_name: str) -> Mapping[str, object]:
    try:
        message: Any = json.loads(text)
    except json.JSONDecodeError as error:
        raise McpProtocolError(
            f"MCP Server ‘{server_name}’ 返回了无效 JSON-RPC 文本：{error.msg}。"
        ) from error
    if not isinstance(message, Mapping) or message.get("jsonrpc") != _JSON_RPC_VERSION:
        raise McpProtocolError(f"MCP Server ‘{server_name}’ 返回了无效 JSON-RPC 消息。")
    return message


def _format_json_rpc_error(error: object) -> str:
    if not isinstance(error, Mapping):
        return "MCP JSON-RPC 响应包含无效 error。"
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, int) or not isinstance(message, str) or not message:
        return "MCP JSON-RPC 响应包含无效 error。"
    return f"MCP JSON-RPC 请求失败（{code}）：{message}。"


def _to_mcp_tool_definition(raw_tool: object) -> McpToolDefinition:
    if not isinstance(raw_tool, Mapping):
        raise McpProtocolError("MCP tools/list 的每个工具定义必须是对象。")
    try:
        return McpToolDefinition(
            name=raw_tool.get("name"),
            description=raw_tool.get("description"),
            input_schema=raw_tool.get("inputSchema"),
            annotations=McpToolAnnotations.from_mcp(raw_tool.get("annotations")),
        )
    except (TypeError, ValueError) as error:
        raise McpProtocolError(f"MCP tools/list 返回了无效工具定义：{error}") from error
