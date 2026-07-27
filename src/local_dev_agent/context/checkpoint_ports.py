"""历史摘要检查点的持久化端口。"""

from typing import Protocol

from .checkpoints import HistorySummaryCheckpoint
from .budget import ContextInputSnapshot


class HistorySummaryCheckpointRepository(Protocol):
    """保存并读取按会话归属的独立历史摘要检查点。"""

    def load(self, session_id: str) -> HistorySummaryCheckpoint | None:
        """返回会话的检查点；不存在时返回 None。"""

    def save(self, checkpoint: HistorySummaryCheckpoint) -> None:
        """原子替换会话当前检查点，不修改 Conversation Transcript。"""


class HistorySummaryCheckpointRebuilder(Protocol):
    """始终从完整原始历史重建检查点的可替换端口。"""

    def rebuild(
        self,
        snapshot: ContextInputSnapshot,
        *,
        desired_covered_message_count: int,
    ) -> HistorySummaryCheckpoint:
        """根据完整原始快照创建一个覆盖安全边界的检查点。"""
