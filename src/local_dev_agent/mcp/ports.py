"""MCP 领域依赖的协议端口，不绑定 stdio 或 JSON-RPC 实现。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Protocol, Sequence, runtime_checkable

from local_dev_agent.mcp.schema import (
    McpServerConfiguration,
    McpToolAnnotations,
    McpToolDefinition,
)


@dataclass(frozen=True)
class McpCallContext:
    """关联一次外部调用与本地会话、运行和工具调用的不可变上下文。"""

    session_id: str
    run_id: str
    step_id: str
    call_id: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("run_id", self.run_id),
            ("step_id", self.step_id),
            ("call_id", self.call_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"MCP 调用上下文的 {field_name} 必须是非空字符串。")


@dataclass(frozen=True)
class McpCallResult:
    """已由传输适配器转换为 JSON 兼容内容的 MCP 工具结果。"""

    content: tuple[Mapping[str, object], ...]
    structured_content: Mapping[str, object] | None = None
    is_error: bool = False

    def __post_init__(self) -> None:
        if not self.content or not all(isinstance(item, Mapping) for item in self.content):
            raise ValueError("MCP 工具结果 content 必须是非空对象数组。")
        if self.structured_content is not None and not isinstance(self.structured_content, Mapping):
            raise ValueError("MCP 工具结果 structured_content 必须是对象或空值。")
        if not isinstance(self.is_error, bool):
            raise ValueError("MCP 工具结果 is_error 必须是布尔值。")
        object.__setattr__(
            self,
            "content",
            tuple(_copy_json_mapping(item, field_name="MCP 工具结果 content") for item in self.content),
        )
        if self.structured_content is not None:
            object.__setattr__(
                self,
                "structured_content",
                _copy_json_mapping(
                    self.structured_content,
                    field_name="MCP 工具结果 structured_content",
                ),
            )


class McpClient(Protocol):
    """一次已建立连接可执行的 MCP 协议能力。"""

    def list_tools(self, *, context: McpCallContext | None = None) -> Sequence[McpToolDefinition]:
        """执行 tools/list 并返回已校验的领域工具定义。"""

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        context: McpCallContext,
    ) -> McpCallResult:
        """执行 tools/call，并保留本地调用关联信息。"""

    def close(self) -> None:
        """关闭一次连接持有的资源。"""


class McpClientConnector(Protocol):
    """由具体传输适配器实现的连接创建端口。"""

    def connect(
        self, server: McpServerConfiguration, *, context: McpCallContext | None = None
    ) -> McpClient:
        """连接一个已配置的 MCP Server。"""


class McpServerCatalog(Protocol):
    """组合根提供的已配置 Server 查询端口。"""

    def get(self, name: str) -> McpServerConfiguration | None:
        """按配置名查询一个 Server，不进行网络发现。"""


class McpToolPool(Protocol):
    """将已发现工具作为一个整体加入本地工具池的端口。"""

    def register(
        self,
        *,
        server: McpServerConfiguration,
        client: McpClient,
        tools: Sequence[McpToolDefinition],
    ) -> tuple[str, ...]:
        """原子注册工具，并返回暴露给模型的稳定公开名称。"""


@runtime_checkable
class McpToolAnnotationsCatalog(Protocol):
    """向权限策略提供已注册 MCP 工具的风险提示，缺失时必须保守处理。"""

    def get_annotations(self, public_tool_name: str) -> McpToolAnnotations | None:
        """返回工具的已校验标注；未知名称返回空值。"""


def _copy_json_mapping(value: Mapping[str, object], *, field_name: str) -> Mapping[str, object]:
    try:
        copied = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} 必须只包含 JSON 兼容的数据类型。") from error
    if not isinstance(copied, dict):
        raise AssertionError("JSON 对象复制后必须仍为对象。")
    return copied
