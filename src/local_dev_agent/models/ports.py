"""模型调用的内容块协议，隔离具体 Provider 的响应结构。"""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次纯文本模型调用所需的最小上下文。"""

    session_id: str
    run_id: str
    user_input: str


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

        if not self.text:
            raise ValueError("模型文本块不能为空。")


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    """模型请求应用执行工具时返回的名称、标识和参数。"""

    tool_use_id: str
    name: str
    input: Mapping[str, object]

    def __post_init__(self) -> None:
        """冻结顶层参数映射，避免调用方在校验前静默修改参数。"""

        if not self.tool_use_id:
            raise ValueError("工具调用块必须包含非空调用标识。")
        if not self.name:
            raise ValueError("工具调用块必须包含非空工具名称。")
        object.__setattr__(self, "input", MappingProxyType(dict(self.input)))


ModelContentBlock = TextBlock | ToolUseBlock


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
