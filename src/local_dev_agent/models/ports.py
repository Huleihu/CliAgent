"""模型调用的最小稳定协议。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次纯文本模型调用所需的最小上下文。"""

    session_id: str
    run_id: str
    user_input: str


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """一次纯文本模型调用返回的最小结果。"""

    text: str


class ModelClient(Protocol):
    """由 Runtime 调用、可替换为真实 Provider 的模型端口。"""

    def generate(self, request: ModelRequest) -> ModelResponse:
        """根据规范化请求生成一条文本响应。"""
