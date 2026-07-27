"""历史摘要检查点的持久化端口。"""

from typing import Protocol

from .checkpoints import HistorySummaryCheckpoint


class HistorySummaryCheckpointRepository(Protocol):
    """保存并读取按会话归属的独立历史摘要检查点。"""

    def load(self, session_id: str) -> HistorySummaryCheckpoint | None:
        """返回会话的检查点；不存在时返回 None。"""

    def save(self, checkpoint: HistorySummaryCheckpoint) -> None:
        """原子替换会话当前检查点，不修改 Conversation Transcript。"""
