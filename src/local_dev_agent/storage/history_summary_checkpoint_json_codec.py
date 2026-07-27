"""历史摘要检查点的版本化 JSON 编解码。"""

from __future__ import annotations

from typing import Any, Mapping

from local_dev_agent.context.checkpoints import (
    HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION,
    HistorySummaryCheckpoint,
)

_ENTITY_TYPE = "history_summary_checkpoint"


def encode_history_summary_checkpoint(
    checkpoint: HistorySummaryCheckpoint,
) -> dict[str, object]:
    """将检查点转换为可读、带版本的 JSON 对象。"""

    if not isinstance(checkpoint, HistorySummaryCheckpoint):
        raise ValueError("checkpoint 必须是 HistorySummaryCheckpoint 对象。")
    return {
        "schema_version": checkpoint.schema_version,
        "entity_type": _ENTITY_TYPE,
        "session_id": checkpoint.session_id,
        "covered_message_count": checkpoint.covered_message_count,
        "source_checksum": checkpoint.source_checksum,
        "summary": checkpoint.summary,
    }


def decode_history_summary_checkpoint(
    payload: dict[str, Any],
) -> HistorySummaryCheckpoint:
    """验证版本和字段后恢复检查点，拒绝未知格式。"""

    schema_version = payload.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION
        or payload.get("entity_type") != _ENTITY_TYPE
    ):
        raise ValueError("历史摘要检查点文件结构不受支持。")
    return HistorySummaryCheckpoint(
        session_id=_get_text(payload, "session_id"),
        covered_message_count=_get_positive_integer(payload, "covered_message_count"),
        source_checksum=_get_text(payload, "source_checksum"),
        summary=_get_text(payload, "summary"),
        schema_version=schema_version,
    )


def _get_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"历史摘要检查点字段“{field_name}”必须是非空字符串。")
    return value


def _get_positive_integer(payload: Mapping[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"历史摘要检查点字段“{field_name}”必须是正整数。")
    return value
