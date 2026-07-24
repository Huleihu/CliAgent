"""会话 Transcript 的版本化 JSON 编解码。"""

from __future__ import annotations

from typing import Any, Mapping

from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

SCHEMA_VERSION = 1


def encode_conversation(
    session_id: str,
    messages: tuple[ModelMessage, ...],
) -> dict[str, object]:
    """将会话消息历史转换为带版本的可读 JSON 数据。"""

    return {
        "schema_version": SCHEMA_VERSION,
        "entity_type": "conversation",
        "session_id": session_id,
        "messages": [_encode_message(message) for message in messages],
    }


def decode_conversation(payload: dict[str, Any]) -> tuple[str, tuple[ModelMessage, ...]]:
    """验证并恢复会话标识与完整消息顺序。"""

    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("entity_type") != "conversation"
    ):
        raise ValueError("会话消息文件结构不受支持。")
    session_id = _get_text(payload, "session_id")
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list) or not all(
        isinstance(message, dict) for message in raw_messages
    ):
        raise ValueError("会话消息文件的 messages 必须是对象列表。")
    return session_id, tuple(_decode_message(message) for message in raw_messages)


def _encode_message(message: ModelMessage) -> dict[str, object]:
    return {
        "role": message.role.value,
        "content": [_encode_content_block(block) for block in message.content],
    }


def _encode_content_block(block: object) -> dict[str, object]:
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
    raise ValueError("会话消息包含不支持的内容块。")


def _decode_message(payload: dict[str, Any]) -> ModelMessage:
    raw_content = payload.get("content")
    if not isinstance(raw_content, list) or not all(
        isinstance(block, dict) for block in raw_content
    ):
        raise ValueError("会话消息内容必须是对象列表。")
    return ModelMessage(
        role=MessageRole(_get_text(payload, "role")),
        content=tuple(_decode_content_block(block) for block in raw_content),
    )


def _decode_content_block(payload: dict[str, Any]) -> TextBlock | ToolUseBlock | ToolResultBlock:
    block_type = _get_text(payload, "type")
    if block_type == "text":
        return TextBlock(text=_get_text(payload, "text"))
    if block_type == "tool_use":
        return ToolUseBlock(
            tool_use_id=_get_text(payload, "tool_use_id"),
            name=_get_text(payload, "name"),
            input=_get_object(payload, "input"),
        )
    if block_type == "tool_result":
        is_error = payload.get("is_error", False)
        if not isinstance(is_error, bool):
            raise ValueError("工具结果的 is_error 必须是布尔值。")
        return ToolResultBlock(
            tool_use_id=_get_text(payload, "tool_use_id"),
            content=_get_object(payload, "content"),
            is_error=is_error,
        )
    raise ValueError(f"会话消息包含不支持的内容块类型“{block_type}”。")


def _get_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"会话消息字段“{field_name}”必须是非空字符串。")
    return value


def _get_object(payload: Mapping[str, Any], field_name: str) -> Mapping[str, object]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"会话消息字段“{field_name}”必须是对象。")
    return value
