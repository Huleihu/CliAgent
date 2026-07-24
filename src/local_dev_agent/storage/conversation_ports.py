"""跨 Run 会话消息 Transcript 的稳定存储端口。"""

from collections.abc import Sequence
from typing import Protocol

from local_dev_agent.models import ModelMessage


class ConversationRepository(Protocol):
    """保存并读取按 Session 归属的完整模型消息历史。"""

    def get_messages(self, session_id: str) -> Sequence[ModelMessage]:
        """按会话标识读取消息历史；不存在时返回空序列。"""

    def append_messages(self, session_id: str, messages: Sequence[ModelMessage]) -> None:
        """按原始顺序追加不可变消息，不修改既有历史。"""
