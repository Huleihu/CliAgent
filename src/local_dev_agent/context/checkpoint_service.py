"""协调检查点读取、视图恢复与完整历史重建，不触碰 Runtime。"""

from __future__ import annotations

from .budget import ContextInputSnapshot
from .checkpoint_ports import (
    HistorySummaryCheckpointRebuilder,
    HistorySummaryCheckpointRepository,
)
from .checkpoint_rebuilder import require_history_summary_checkpoint_rebuilder
from .checkpoint_views import build_history_summary_checkpoint_view


class HistorySummaryCheckpointService:
    """将可信检查点转换为请求视图，并负责保存由完整历史重建的结果。"""

    def __init__(
        self,
        repository: HistorySummaryCheckpointRepository,
        rebuilder: HistorySummaryCheckpointRebuilder,
    ) -> None:
        if not hasattr(repository, "load") or not hasattr(repository, "save"):
            raise ValueError("repository 必须提供 load 和 save 方法。")
        self._repository = repository
        self._rebuilder = require_history_summary_checkpoint_rebuilder(rebuilder)

    def restore_view(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        """返回已验证的检查点视图；不存在检查点时原样返回完整快照。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        checkpoint = self._repository.load(snapshot.session_id)
        if checkpoint is None:
            return snapshot
        return build_history_summary_checkpoint_view(snapshot, checkpoint)

    def rebuild_view_from_full_history(
        self,
        snapshot: ContextInputSnapshot,
        *,
        desired_covered_message_count: int,
    ) -> ContextInputSnapshot:
        """仅从传入的完整原始快照重建、保存并返回新的检查点视图。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        checkpoint = self._rebuilder.rebuild(
            snapshot,
            desired_covered_message_count=desired_covered_message_count,
        )
        self._repository.save(checkpoint)
        return build_history_summary_checkpoint_view(snapshot, checkpoint)
