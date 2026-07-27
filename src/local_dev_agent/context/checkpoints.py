"""历史摘要检查点的纯领域契约、来源校验和与安全边界规则。"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION = 1
"""当前支持的历史摘要检查点文件与领域对象版本。"""

_SHA256_PREFIX = "sha256:"


class HistorySummaryCheckpointSourceMismatchError(ValueError):
    """当检查点不再对应其声明的原始 Transcript 前缀时抛出。"""


def _require_nonempty_text(field_name: str, value: str) -> str:
    """规范化必要文本，避免检查点失去归属或可读摘要。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


def _require_positive_integer(field_name: str, value: int) -> int:
    """拒绝布尔值、零和负数，使覆盖边界保持明确。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"字段“{field_name}”必须是正整数。")
    return value


@dataclass(frozen=True, slots=True)
class HistorySummaryCheckpoint:
    """一段完整原始 Transcript 前缀的可验证摘要缓存。"""

    session_id: str
    covered_message_count: int
    source_checksum: str
    summary: str
    schema_version: int = HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """拒绝不受支持的版本和不完整元数据，防止后续静默使用。"""

        object.__setattr__(self, "session_id", _require_nonempty_text("session_id", self.session_id))
        _require_positive_integer("covered_message_count", self.covered_message_count)
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION
        ):
            raise ValueError("历史摘要检查点版本不受支持。")
        if not _is_sha256_checksum(self.source_checksum):
            raise ValueError("字段“source_checksum”必须是 SHA-256 校验和。")
        object.__setattr__(self, "summary", _require_nonempty_text("summary", self.summary))


def select_safe_history_checkpoint_boundary(
    messages: tuple[ModelMessage, ...],
    desired_covered_message_count: int,
) -> int:
    """返回不拆开相邻工具调用与结果的最大安全覆盖边界。"""

    _require_messages(messages)
    desired_covered_message_count = _require_positive_integer(
        "desired_covered_message_count",
        desired_covered_message_count,
    )
    if desired_covered_message_count > len(messages):
        raise ValueError("检查点覆盖消息数不能超过历史消息总数。")

    boundary = desired_covered_message_count
    while _boundary_splits_tool_exchange(messages, boundary):
        boundary -= 1
    if boundary == 0:
        raise ValueError("无法在不拆分工具调用与结果的前提下创建检查点。")
    return boundary


def calculate_history_source_checksum(
    *,
    session_id: str,
    messages: tuple[ModelMessage, ...],
) -> str:
    """为指定会话的一段原始消息生成稳定 SHA-256 来源校验和。"""

    session_id = _require_nonempty_text("session_id", session_id)
    _require_messages(messages)
    serialized = json.dumps(
        {
            "session_id": session_id,
            "messages": [_message_to_json(message) for message in messages],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return _SHA256_PREFIX + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_history_summary_checkpoint(
    checkpoint: HistorySummaryCheckpoint,
    *,
    session_id: str,
    messages: tuple[ModelMessage, ...],
) -> None:
    """确认检查点归属、边界和来源均与当前完整 Transcript 一致。"""

    if not isinstance(checkpoint, HistorySummaryCheckpoint):
        raise ValueError("checkpoint 必须是 HistorySummaryCheckpoint 对象。")
    session_id = _require_nonempty_text("session_id", session_id)
    _require_messages(messages)
    if checkpoint.session_id != session_id:
        raise HistorySummaryCheckpointSourceMismatchError("历史摘要检查点会话标识不匹配。")
    if checkpoint.covered_message_count > len(messages):
        raise HistorySummaryCheckpointSourceMismatchError(
            "历史摘要检查点覆盖范围超过当前 Transcript。"
        )
    if _boundary_splits_tool_exchange(messages, checkpoint.covered_message_count):
        raise HistorySummaryCheckpointSourceMismatchError(
            "历史摘要检查点边界拆分了工具调用与结果。"
        )
    expected_checksum = calculate_history_source_checksum(
        session_id=session_id,
        messages=messages[: checkpoint.covered_message_count],
    )
    if not hmac.compare_digest(checkpoint.source_checksum, expected_checksum):
        raise HistorySummaryCheckpointSourceMismatchError(
            "历史摘要检查点来源校验和不匹配。"
        )


def _require_messages(messages: tuple[ModelMessage, ...]) -> None:
    """保持校验输入与持久化 Transcript 的不可变消息协议一致。"""

    if not isinstance(messages, tuple) or not messages:
        raise ValueError("messages 必须是非空 ModelMessage 元组。")
    if not all(isinstance(message, ModelMessage) for message in messages):
        raise ValueError("messages 必须是非空 ModelMessage 元组。")


def _boundary_splits_tool_exchange(
    messages: tuple[ModelMessage, ...],
    boundary: int,
) -> bool:
    """仅在相邻消息确有同一调用标识时认定边界拆开了工具交互。"""

    if boundary == 0 or boundary == len(messages):
        return False
    previous_message = messages[boundary - 1]
    next_message = messages[boundary]
    if (
        previous_message.role is not MessageRole.ASSISTANT
        or next_message.role is not MessageRole.USER
    ):
        return False
    tool_use_ids = {
        block.tool_use_id
        for block in previous_message.content
        if isinstance(block, ToolUseBlock)
    }
    tool_result_ids = {
        block.tool_use_id
        for block in next_message.content
        if isinstance(block, ToolResultBlock)
    }
    return bool(tool_use_ids & tool_result_ids)


def _is_sha256_checksum(value: object) -> bool:
    """只接受标准的小写十六进制 SHA-256 表示，避免多种等价格式混用。"""

    if not isinstance(value, str) or not value.startswith(_SHA256_PREFIX):
        return False
    digest = value.removeprefix(_SHA256_PREFIX)
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _message_to_json(message: ModelMessage) -> dict[str, object]:
    """以与 Provider 无关的稳定结构表示原始消息，作为校验和来源。"""

    return {
        "role": message.role.value,
        "content": [_content_block_to_json(block) for block in message.content],
    }


def _content_block_to_json(block: object) -> dict[str, object]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "tool_use_id": block.tool_use_id,
            "name": block.name,
            "input": dict(block.input),
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": dict(block.content),
            "is_error": block.is_error,
        }
    raise ValueError("历史摘要检查点消息包含不受支持的内容块。")
