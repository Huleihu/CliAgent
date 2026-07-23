"""模型调用的内容块、对话消息与 Provider 解耦协议。"""

import json
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol


def _require_non_empty_text(field_name: str, value: str) -> None:
    """拒绝空标识和空文本，避免产生无法关联或无意义的消息。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


def _freeze_json_mapping(
    field_name: str,
    value: Mapping[str, object],
) -> Mapping[str, object]:
    """验证并冻结顶层 JSON 对象，保护调用前后的消息快照。"""

    if not isinstance(value, Mapping):
        raise ValueError(f"字段“{field_name}”必须是对象。")
    copied_value = dict(value)
    try:
        json.dumps(copied_value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"字段“{field_name}”必须只包含 JSON 原生值。") from error
    return MappingProxyType(copied_value)


class StopReason(StrEnum):
    """模型结束本轮生成的原因。"""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    REFUSAL = "refusal"


@dataclass(frozen=True, slots=True)
class TextBlock:
    """模型返回的一段自然语言文本。"""

    text: str

    def __post_init__(self) -> None:
        """拒绝空文本，避免将空输出误判为任务完成。"""

        if not isinstance(self.text, str) or not self.text:
            raise ValueError("模型文本块不能为空。")


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    """模型请求应用执行工具时返回的名称、标识和参数。"""

    tool_use_id: str
    name: str
    input: Mapping[str, object]

    def __post_init__(self) -> None:
        """冻结顶层参数映射，避免调用方在校验前静默修改参数。"""

        _require_non_empty_text("tool_use_id", self.tool_use_id)
        _require_non_empty_text("name", self.name)
        object.__setattr__(self, "input", _freeze_json_mapping("input", self.input))


ModelContentBlock = TextBlock | ToolUseBlock


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    """表示一次工具执行后可回填给模型的结构化结果。"""

    tool_use_id: str
    content: Mapping[str, object]
    is_error: bool = False

    def __post_init__(self) -> None:
        """保留调用关联并冻结结果，避免回填前被工具实现静默篡改。"""

        _require_non_empty_text("tool_use_id", self.tool_use_id)
        if not isinstance(self.is_error, bool):
            raise ValueError("字段“is_error”必须是布尔值。")
        object.__setattr__(
            self,
            "content",
            _freeze_json_mapping("content", self.content),
        )


class MessageRole(StrEnum):
    """多轮对话中一条消息的发送方。"""

    USER = "user"
    ASSISTANT = "assistant"


ConversationContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """一条不可变对话消息，显式保留发送方和内容块顺序。"""

    role: MessageRole
    content: tuple[ConversationContentBlock, ...]

    def __post_init__(self) -> None:
        """限制各角色可携带的内容，提前发现不合法的 Provider 请求。"""

        if not isinstance(self.content, tuple) or not self.content:
            raise ValueError("模型消息必须包含至少一个内容块。")

        allowed_types = {
            MessageRole.USER: (TextBlock, ToolResultBlock),
            MessageRole.ASSISTANT: (TextBlock, ToolUseBlock),
        }[self.role]
        if not all(isinstance(block, allowed_types) for block in self.content):
            raise ValueError(f"角色“{self.role}”包含不允许的内容块。")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次模型调用所需的会话关联和可扩展的多轮对话上下文。"""

    session_id: str
    run_id: str
    user_input: str | None = None
    messages: tuple[ModelMessage, ...] = ()

    def __post_init__(self) -> None:
        """兼容旧的单文本调用，同时拒绝两种上下文来源混用。"""

        _require_non_empty_text("session_id", self.session_id)
        _require_non_empty_text("run_id", self.run_id)
        if self.user_input is not None:
            _require_non_empty_text("user_input", self.user_input)
        if not isinstance(self.messages, tuple):
            raise ValueError("模型请求的 messages 必须是元组。")
        if self.user_input is not None and self.messages:
            raise ValueError("模型请求不能同时提供 user_input 和 messages。")
        if self.user_input is None and not self.messages:
            raise ValueError("模型请求必须提供 user_input 或 messages。")

    @classmethod
    def from_messages(
        cls,
        *,
        session_id: str,
        run_id: str,
        messages: tuple[ModelMessage, ...],
    ) -> "ModelRequest":
        """创建携带完整多轮上下文的请求。"""

        return cls(session_id=session_id, run_id=run_id, messages=messages)

    @property
    def conversation(self) -> tuple[ModelMessage, ...]:
        """返回规范化消息历史，为旧单文本请求补齐首条用户消息。"""

        if self.messages:
            return self.messages
        return (
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock(text=self.user_input or ""),),
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """一次模型调用的停止原因与可包含多个块的规范化结果。"""

    stop_reason: StopReason
    content: tuple[ModelContentBlock, ...]

    def __post_init__(self) -> None:
        """确保工具调用停止原因确实携带至少一个工具调用块。"""

        if not self.content:
            raise ValueError("模型响应至少必须包含一个内容块。")
        if self.stop_reason is StopReason.TOOL_USE and not any(
            isinstance(block, ToolUseBlock) for block in self.content
        ):
            raise ValueError("工具调用停止原因必须包含工具调用块。")

    @classmethod
    def text_completion(cls, text: str) -> "ModelResponse":
        """创建表示正常文本结束的最小响应。"""

        return cls(
            stop_reason=StopReason.END_TURN,
            content=(TextBlock(text=text),),
        )

    @property
    def text_blocks(self) -> tuple[TextBlock, ...]:
        """返回响应中的全部文本块，供文本完成路径读取。"""

        return tuple(
            block for block in self.content if isinstance(block, TextBlock)
        )

    @property
    def text(self) -> str:
        """合并文本块，兼容纯文本调用方的直接读取方式。"""

        return "".join(block.text for block in self.text_blocks)


class ModelClient(Protocol):
    """由 Runtime 调用、可替换为真实 Provider 的模型端口。"""

    def generate(self, request: ModelRequest) -> ModelResponse:
        """根据规范化请求生成一条文本响应或工具调用请求。"""
