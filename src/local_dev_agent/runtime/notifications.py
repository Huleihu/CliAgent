"""向后续模型请求提供待处理 user 文本的通用端口。"""

from collections.abc import Sequence
from typing import Protocol


class PendingUserMessageSource(Protocol):
    """按 Session 一次性排出可合入 user 消息的文本通知。"""

    def drain(self, *, session_id: str) -> Sequence[str]:
        """返回并消费指定 Session 当前待处理的非空文本通知。"""
