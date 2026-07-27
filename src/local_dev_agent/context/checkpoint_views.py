"""从已验证检查点构造“历史摘要加原始尾部”的派生请求视图。"""

from __future__ import annotations

from local_dev_agent.models import MessageRole, ModelMessage, TextBlock

from .budget import ContextInputSnapshot
from .checkpoints import (
    HistorySummaryCheckpoint,
    validate_history_summary_checkpoint,
)


def build_history_summary_checkpoint_view(
    snapshot: ContextInputSnapshot,
    checkpoint: HistorySummaryCheckpoint,
) -> ContextInputSnapshot:
    """仅保留请求元数据，并将消息级检查点视图装回新的快照。"""

    if not isinstance(snapshot, ContextInputSnapshot):
        raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
    return ContextInputSnapshot(
        session_id=snapshot.session_id,
        run_id=snapshot.run_id,
        messages=build_history_summary_checkpoint_messages(
            session_id=snapshot.session_id,
            messages=snapshot.messages,
            checkpoint=checkpoint,
        ),
        system_prompt=snapshot.system_prompt,
        tools=snapshot.tools,
    )


def build_history_summary_checkpoint_messages(
    *,
    session_id: str,
    messages: tuple[ModelMessage, ...],
    checkpoint: HistorySummaryCheckpoint,
) -> tuple[ModelMessage, ...]:
    """将可信检查点摘要和未覆盖的原始消息尾部组合为请求消息。"""

    if not isinstance(checkpoint, HistorySummaryCheckpoint):
        raise ValueError("checkpoint 必须是 HistorySummaryCheckpoint 对象。")
    validate_history_summary_checkpoint(
        checkpoint,
        session_id=session_id,
        messages=messages,
    )
    summary_message = ModelMessage(
        role=MessageRole.USER,
        content=(TextBlock(f"[历史摘要检查点]\n\n{checkpoint.summary}"),),
    )
    return (summary_message, *messages[checkpoint.covered_message_count :])
