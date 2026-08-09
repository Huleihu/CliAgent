"""通过 stdio JSON-RPC 与显式配置的本地 MCP 子进程通信。"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from threading import RLock, Thread
from typing import TextIO

from local_dev_agent.mcp.errors import McpConnectionError, McpProtocolError, McpToolCallError
from local_dev_agent.mcp.ports import McpCallContext, McpCallResult, McpClient
from local_dev_agent.mcp.schema import (
    McpServerConfiguration,
    McpToolAnnotations,
    McpToolDefinition,
)

_JSON_RPC_VERSION = "2.0"
_MCP_PROTOCOL_VERSION = "2025-03-26"
_CONTEXT_META_KEY = "io.local-dev-agent/context"


@dataclass(frozen=True)
class StdioMcpLaunchConfiguration:
    """一个本地 MCP 子进程的显式启动配置，不读取市场或网络发现结果。"""

    server_name: str
    command: str
    arguments: tuple[str, ...] = ()
    cwd: Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.server_name, str) or not self.server_name.strip():
            raise ValueError("stdio MCP 配置的 server_name 必须是非空字符串。")
        _validate_process_text("command", self.command)
        if not isinstance(self.arguments, tuple):
            raise ValueError("stdio MCP 配置的 arguments 必须是字符串元组。")
        for argument in self.arguments:
            _validate_process_text("arguments 元素", argument)
        if self.cwd is not None:
            if not isinstance(self.cwd, Path):
                raise ValueError("stdio MCP 配置的 cwd 必须是 Path 或 None。")
            if not self.cwd.is_absolute() or not self.cwd.is_dir():
                raise ValueError("stdio MCP 配置的 cwd 必须是存在的绝对目录。")
        if not isinstance(self.environment, Mapping):
            raise ValueError("stdio MCP 配置的 environment 必须是字符串映射。")
        for key, value in self.environment.items():
            _validate_process_text("environment 键", key)
            _validate_process_text("environment 值", value)
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("stdio MCP 配置的 request_timeout_seconds 必须是正数。")


class StdioMcpClientConnector:
    """按 Server 名启动一个已配置的 stdio MCP 子进程并完成初始化。"""

    def __init__(self, configurations: Sequence[StdioMcpLaunchConfiguration]) -> None:
        self._configurations = {configuration.server_name: configuration for configuration in configurations}
        if len(self._configurations) != len(configurations):
            raise ValueError("stdio MCP 配置的 server_name 不能重复。")

    def connect(
        self, server: McpServerConfiguration, *, context: McpCallContext | None = None
    ) -> McpClient:
        configuration = self._configurations.get(server.name)
        if configuration is None:
            raise McpConnectionError(f"没有为 MCP Server “{server.name}”配置 stdio 启动命令。")
        client = StdioMcpClient.start(configuration)
        try:
            client.initialize(context=context)
        except Exception:
            client.close()
            raise
        return client


class StdioMcpClient:
    """一个进程一条连接的最小 MCP stdio Client，支持初始化、发现、调用和关闭。"""

    def __init__(
        self,
        *,
        configuration: StdioMcpLaunchConfiguration,
        process: subprocess.Popen[str],
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise McpConnectionError("stdio MCP 子进程必须提供 stdin 和 stdout。")
        self._configuration = configuration
        self._process = process
        self._stdin: TextIO = process.stdin
        self._stdout: TextIO = process.stdout
        self._stdout_messages: Queue[object] = Queue()
        self._next_request_id = 1
        self._initialized = False
        self._closed = False
        self._lock = RLock()
        self._reader_thread = Thread(
            target=self._read_stdout,
            name=f"mcp-stdio-reader-{configuration.server_name}",
            daemon=True,
        )
        self._reader_thread.start()

    @classmethod
    def start(cls, configuration: StdioMcpLaunchConfiguration) -> "StdioMcpClient":
        """启动子进程；cwd 仅作用于该子进程，不会改变当前进程工作目录。"""

        environment = os.environ.copy()
        environment.update(dict(configuration.environment))
        try:
            process = subprocess.Popen(
                (configuration.command, *configuration.arguments),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                cwd=str(configuration.cwd) if configuration.cwd is not None else None,
                env=environment,
            )
        except OSError as error:
            raise McpConnectionError(
                f"启动 MCP Server “{configuration.server_name}”的 stdio 子进程失败：{error}"
            ) from error
        return cls(configuration=configuration, process=process)

    def initialize(self, *, context: McpCallContext | None = None) -> None:
        """执行 MCP initialize 握手并发送 initialized 通知。"""

        with self._lock:
            self._ensure_open()
            if self._initialized:
                return
            result = self._request_locked(
                "initialize",
                {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "local-dev-agent", "version": "0.1.0"},
                    **_context_meta(context),
                },
            )
            protocol_version = result.get("protocolVersion")
            if not isinstance(protocol_version, str) or not protocol_version:
                raise McpProtocolError("MCP initialize 响应缺少有效的 protocolVersion。")
            self._notify_locked("notifications/initialized", {})
            self._initialized = True

    def list_tools(self, *, context: McpCallContext | None = None) -> Sequence[McpToolDefinition]:
        """执行可分页的 tools/list，并在本地转换与校验 Server 定义。"""

        with self._lock:
            self._ensure_initialized()
            tools: list[McpToolDefinition] = []
            cursor: str | None = None
            seen_cursors: set[str] = set()
            while True:
                parameters: dict[str, object] = dict(_context_meta(context))
                if cursor is not None:
                    parameters["cursor"] = cursor
                result = self._request_locked("tools/list", parameters)
                raw_tools = result.get("tools")
                if not isinstance(raw_tools, list):
                    raise McpProtocolError("MCP tools/list 响应的 tools 必须是数组。")
                tools.extend(_to_mcp_tool_definition(item) for item in raw_tools)
                next_cursor = result.get("nextCursor")
                if next_cursor is None:
                    return tuple(tools)
                if not isinstance(next_cursor, str) or not next_cursor:
                    raise McpProtocolError("MCP tools/list 响应的 nextCursor 必须是非空字符串或空值。")
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
        """将本地工具调用映射为标准 tools/call，并保留关联元数据。"""

        if not isinstance(name, str) or not name:
            raise McpToolCallError("MCP tools/call 的 name 必须是非空字符串。")
        if not isinstance(arguments, Mapping):
            raise McpToolCallError("MCP tools/call 的 arguments 必须是对象。")
        with self._lock:
            self._ensure_initialized()
            result = self._request_locked(
                "tools/call",
                {
                    "name": name,
                    "arguments": dict(arguments),
                    **_context_meta(context),
                },
            )
        content = result.get("content")
        if (
            not isinstance(content, list)
            or not content
            or not all(isinstance(item, Mapping) for item in content)
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
        """关闭 stdio 并终止本 Client 启动的子进程，不影响其他 Run 的 cwd。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._stdin.close()
            except OSError:
                pass
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)

    def _ensure_initialized(self) -> None:
        self._ensure_open()
        if not self._initialized:
            raise McpConnectionError("MCP stdio 连接尚未完成 initialize。")

    def _ensure_open(self) -> None:
        if self._closed:
            raise McpConnectionError("MCP stdio 连接已经关闭。")
        return_code = self._process.poll()
        if return_code is not None:
            raise McpConnectionError(
                f"MCP Server “{self._configuration.server_name}”已退出，退出码为 {return_code}。"
            )

    def _request_locked(self, method: str, parameters: Mapping[str, object]) -> Mapping[str, object]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._write_locked(
            {"jsonrpc": _JSON_RPC_VERSION, "id": request_id, "method": method, "params": parameters}
        )
        return self._read_response_locked(request_id=request_id, method=method)

    def _notify_locked(self, method: str, parameters: Mapping[str, object]) -> None:
        self._write_locked({"jsonrpc": _JSON_RPC_VERSION, "method": method, "params": parameters})

    def _write_locked(self, message: Mapping[str, object]) -> None:
        try:
            serialized = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            self._stdin.write(serialized + "\n")
            self._stdin.flush()
        except (OSError, TypeError, ValueError) as error:
            raise McpConnectionError(
                f"向 MCP Server “{self._configuration.server_name}”发送 JSON-RPC 消息失败：{error}"
            ) from error

    def _read_response_locked(self, *, request_id: int, method: str) -> Mapping[str, object]:
        while True:
            try:
                raw_message = self._stdout_messages.get(
                    timeout=float(self._configuration.request_timeout_seconds)
                )
            except Empty as error:
                raise McpConnectionError(
                    f"等待 MCP Server “{self._configuration.server_name}”响应 {method} 超时。"
                ) from error
            if raw_message is None:
                return_code = self._process.poll()
                raise McpConnectionError(
                    f"MCP Server “{self._configuration.server_name}”在响应 {method} 前关闭了 stdout，"
                    f"退出码为 {return_code}。"
                )
            if isinstance(raw_message, Exception):
                raise McpConnectionError(
                    f"读取 MCP Server “{self._configuration.server_name}”的 JSON-RPC 响应失败：{raw_message}"
                ) from raw_message
            if not isinstance(raw_message, str):
                raise AssertionError("stdio 读取线程只能传递文本、异常或结束标记。")
            message = _parse_json_rpc_message(
                line=raw_message,
                server_name=self._configuration.server_name,
            )
            if "id" not in message:
                # 本步不实现 Server 主动通知；忽略它以继续等待当前请求响应。
                continue
            if message.get("id") != request_id:
                raise McpProtocolError(
                    f"MCP Server “{self._configuration.server_name}”返回了不匹配的请求 id。"
                )
            error = message.get("error")
            if error is not None:
                raise McpProtocolError(_format_json_rpc_error(error))
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise McpProtocolError(f"MCP {method} 响应缺少对象 result。")
            return result

    def _read_stdout(self) -> None:
        """单独读取 stdout，使请求线程能够对无响应 Server 施加超时。"""

        try:
            for line in self._stdout:
                self._stdout_messages.put(line)
        except (OSError, UnicodeDecodeError) as error:
            self._stdout_messages.put(error)
        finally:
            self._stdout_messages.put(None)


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


def _parse_json_rpc_message(*, line: str, server_name: str) -> Mapping[str, object]:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as error:
        raise McpProtocolError(
            f"MCP Server “{server_name}”返回了无效 JSON-RPC 文本：{error.msg}。"
        ) from error
    if not isinstance(message, Mapping) or message.get("jsonrpc") != _JSON_RPC_VERSION:
        raise McpProtocolError(f"MCP Server “{server_name}”返回了无效 JSON-RPC 消息。")
    return message


def _format_json_rpc_error(error: object) -> str:
    if not isinstance(error, Mapping):
        return "MCP JSON-RPC 响应包含无效 error。"
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, int) or not isinstance(message, str) or not message:
        return "MCP JSON-RPC 响应包含无效 error。"
    return f"MCP JSON-RPC 请求失败（{code}）：{message}。"


def _validate_process_text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"stdio MCP 配置的 {field_name} 必须是不含空字符的非空字符串。")
