"""待办清单快照的版本化 JSON 编解码。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from local_dev_agent.domain.state.timestamps import normalize_utc_timestamp

from .schema import TodoItem, TodoSnapshot, TodoStatus


SCHEMA_VERSION = 1
_ENTITY_TYPE = "todo_list"


def encode_snapshot(snapshot: TodoSnapshot) -> dict[str, object]:
    """将待办快照转换为可读、可演进的 JSON 数据。"""

    return {
        "schema_version": SCHEMA_VERSION,
        "entity_type": _ENTITY_TYPE,
        "state": {
            "todo_list_id": snapshot.todo_list_id,
            "updated_at": snapshot.updated_at.isoformat(),
            "todos": [
                {
                    "content": todo.content,
                    "status": todo.status.value,
                    "active_form": todo.active_form,
                }
                for todo in snapshot.todos
            ],
        },
    }


def decode_snapshot(payload: dict[str, Any]) -> TodoSnapshot:
    """从经过结构校验的 JSON 数据恢复待办快照。"""

    state = _get_state(payload)
    return TodoSnapshot(
        todo_list_id=_get_string(state, "todo_list_id"),
        updated_at=_parse_timestamp(state, "updated_at"),
        todos=tuple(
            TodoItem(
                content=_get_string(item, "content"),
                status=TodoStatus(_get_string(item, "status")),
                active_form=_get_optional_string(item, "active_form"),
            )
            for item in _get_object_list(state, "todos")
        ),
    )


def _get_state(payload: dict[str, Any]) -> dict[str, Any]:
    """校验公共信封，避免错误实体被恢复为待办清单。"""

    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("entity_type") != _ENTITY_TYPE
        or not isinstance(payload.get("state"), dict)
    ):
        raise ValueError("待办清单文件结构不受支持。")
    return payload["state"]


def _get_string(payload: dict[str, Any], field_name: str) -> str:
    """读取非空字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"待办清单文件字段“{field_name}”必须是非空字符串。")
    return value


def _get_optional_string(payload: dict[str, Any], field_name: str) -> str | None:
    """读取允许为空值的字符串字段。"""

    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"待办清单文件字段“{field_name}”必须是字符串或空值。")
    return value


def _get_object_list(payload: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    """读取由对象组成的待办列表。"""

    value = payload.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"待办清单文件字段“{field_name}”必须是对象列表。")
    return value


def _parse_timestamp(payload: dict[str, Any], field_name: str) -> datetime:
    """解析并统一为 UTC，拒绝持久化歧义的无时区时间。"""

    value = _get_string(payload, field_name)
    try:
        return normalize_utc_timestamp(
            datetime.fromisoformat(value),
            subject="待办清单",
        )
    except ValueError as error:
        raise ValueError(
            f"待办清单文件字段“{field_name}”不是有效的带时区时间。"
        ) from error
