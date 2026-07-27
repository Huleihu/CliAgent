"""以复制方式裁剪过旧消息和工具结果，保持完整工具调用配对。"""

from __future__ import annotations

import json

from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from .budget import ContextInputSnapshot


def _require_positive_integer(field_name: str, value: int) -> int:
    """拒绝布尔值、零和负数，保持裁剪边界可预测。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"字段“{field_name}”必须是正整数。")
    return value


def _require_nonnegative_integer(field_name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"字段“{field_name}”必须是非负整数。")
    return value


def _new_snapshot(
    snapshot: ContextInputSnapshot,
    messages: tuple[ModelMessage, ...],
) -> ContextInputSnapshot:
    """复用稳定请求元数据，只替换派生上下文的消息视图。"""

    return ContextInputSnapshot(
        session_id=snapshot.session_id,
        run_id=snapshot.run_id,
        messages=messages,
        system_prompt=snapshot.system_prompt,
        tools=snapshot.tools,
    )


def _message_has_tool_use(message: ModelMessage) -> bool:
    return message.role is MessageRole.ASSISTANT and any(
        isinstance(block, ToolUseBlock) for block in message.content
    )


def _is_tool_result_message(message: ModelMessage) -> bool:
    return message.role is MessageRole.USER and any(
        isinstance(block, ToolResultBlock) for block in message.content
    )


class ConversationSnipCompactor:
    """L1：裁剪历史中段消息，同时不拆开相邻的工具调用与结果。"""

    def __init__(
        self,
        *,
        max_message_count: int = 50,
        keep_head_message_count: int = 3,
    ) -> None:
        max_message_count = _require_positive_integer(
            "max_message_count",
            max_message_count,
        )
        keep_head_message_count = _require_positive_integer(
            "keep_head_message_count",
            keep_head_message_count,
        )
        if keep_head_message_count >= max_message_count:
            raise ValueError("keep_head_message_count 必须小于 max_message_count。")
        self._max_message_count = max_message_count
        self._keep_head_message_count = keep_head_message_count

    def compact(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        """保留首尾消息，并用一条明确占位消息替换中段历史。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        messages = snapshot.messages
        if len(messages) <= self._max_message_count:
            return snapshot

        head_end = self._keep_head_message_count
        tail_start = len(messages) - (
            self._max_message_count - self._keep_head_message_count
        )
        head_end = self._extend_head_past_tool_results(messages, head_end)
        tail_start = self._rewind_tail_to_tool_use(messages, tail_start)
        if head_end >= tail_start:
            return snapshot

        snipped_count = tail_start - head_end
        placeholder = ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock(f"[已裁剪中间的 {snipped_count} 条历史消息。]"),),
        )
        return _new_snapshot(
            snapshot,
            messages=(*messages[:head_end], placeholder, *messages[tail_start:]),
        )

    @staticmethod
    def _extend_head_past_tool_results(
        messages: tuple[ModelMessage, ...],
        head_end: int,
    ) -> int:
        """避免首段末尾留下没有对应结果的工具调用。"""

        if head_end == 0 or not _message_has_tool_use(messages[head_end - 1]):
            return head_end
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1
        return head_end

    @staticmethod
    def _rewind_tail_to_tool_use(
        messages: tuple[ModelMessage, ...],
        tail_start: int,
    ) -> int:
        """避免尾段开头只保留工具结果而删除其触发调用。"""

        if (
            tail_start > 0
            and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])
        ):
            return tail_start - 1
        return tail_start


class ToolResultMicroCompactor:
    """L2：仅将较早且较大的工具结果替换为可重新获取的占位提示。"""

    def __init__(
        self,
        *,
        keep_recent_result_count: int = 3,
        minimum_result_bytes: int = 120,
    ) -> None:
        self._keep_recent_result_count = _require_nonnegative_integer(
            "keep_recent_result_count",
            keep_recent_result_count,
        )
        self._minimum_result_bytes = _require_positive_integer(
            "minimum_result_bytes",
            minimum_result_bytes,
        )

    def compact(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        """复制包含旧工具结果的消息，只替换超过下限的历史结果块。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        tool_results = tuple(self._collect_tool_results(snapshot.messages))
        if len(tool_results) <= self._keep_recent_result_count:
            return snapshot

        replacements: dict[int, list[object]] = {}
        for message_index, block_index, block in tool_results[
            : -self._keep_recent_result_count or None
        ]:
            if self._content_size_bytes(block) < self._minimum_result_bytes:
                continue
            blocks = replacements.setdefault(
                message_index,
                list(snapshot.messages[message_index].content),
            )
            blocks[block_index] = ToolResultBlock(
                tool_use_id=block.tool_use_id,
                is_error=block.is_error,
                content={
                    "notice": "较早工具结果已压缩；如需完整内容，请重新执行该工具调用。"
                },
            )
        if not replacements:
            return snapshot

        compacted_messages = list(snapshot.messages)
        for message_index, blocks in replacements.items():
            original_message = snapshot.messages[message_index]
            compacted_messages[message_index] = ModelMessage(
                role=original_message.role,
                content=tuple(blocks),
            )
        return _new_snapshot(snapshot, messages=tuple(compacted_messages))

    @staticmethod
    def _collect_tool_results(
        messages: tuple[ModelMessage, ...],
    ) -> list[tuple[int, int, ToolResultBlock]]:
        """按对话顺序收集结果块，使最近结果判断不依赖消息分组方式。"""

        return [
            (message_index, block_index, block)
            for message_index, message in enumerate(messages)
            for block_index, block in enumerate(message.content)
            if isinstance(block, ToolResultBlock)
        ]

    @staticmethod
    def _content_size_bytes(block: ToolResultBlock) -> int:
        serialized = json.dumps(
            dict(block.content),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return len(serialized.encode("utf-8"))
