"""从完整原始历史生成历史摘要检查点。"""

from __future__ import annotations

from .budget import ContextInputSnapshot
from .checkpoint_ports import HistorySummaryCheckpointRebuilder
from .checkpoints import (
    HistorySummaryCheckpoint,
    calculate_history_source_checksum,
    select_safe_history_checkpoint_boundary,
)
from .summary import ConversationSummarizer


class FullHistorySummaryCheckpointRebuilder:
    """只对完整原始 Transcript 前缀摘要，避免长期摘要再摘要。"""

    def __init__(self, summarizer: ConversationSummarizer) -> None:
        if not hasattr(summarizer, "summarize"):
            raise ValueError("summarizer 必须提供 summarize 方法。")
        self._summarizer = summarizer

    def rebuild(
        self,
        snapshot: ContextInputSnapshot,
        *,
        desired_covered_message_count: int,
    ) -> HistorySummaryCheckpoint:
        """以安全原始前缀生成摘要；调用方决定何时保存或使用该检查点。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        covered_message_count = select_safe_history_checkpoint_boundary(
            snapshot.messages,
            desired_covered_message_count,
        )
        source_snapshot = ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=snapshot.messages[:covered_message_count],
            system_prompt=snapshot.system_prompt,
            tools=snapshot.tools,
        )
        summary = self._summarizer.summarize(source_snapshot)
        return HistorySummaryCheckpoint(
            session_id=snapshot.session_id,
            covered_message_count=covered_message_count,
            source_checksum=calculate_history_source_checksum(
                session_id=snapshot.session_id,
                messages=source_snapshot.messages,
            ),
            summary=summary,
        )


def require_history_summary_checkpoint_rebuilder(
    rebuilder: HistorySummaryCheckpointRebuilder,
) -> HistorySummaryCheckpointRebuilder:
    """在组合根边界验证重建器端口，避免运行时缺失完整历史重建能力。"""

    if not hasattr(rebuilder, "rebuild"):
        raise ValueError("rebuilder 必须提供 rebuild 方法。")
    return rebuilder
