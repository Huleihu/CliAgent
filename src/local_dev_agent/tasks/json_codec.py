"""任务快照的版本化 JSON 编解码。"""

from __future__ import annotations

from typing import Any

from .schema import Task, TaskStatus


SCHEMA_VERSION = 1
_ENTITY_TYPE = "task"


def encode_task(task: Task) -> dict[str, object]:
    """将任务快照编码为可读、可演进的 JSON 对象。"""

    if not isinstance(task, Task):
        raise TypeError("task 必须是 Task 对象。")
    return {
        "schema_version": SCHEMA_VERSION,
        "entity_type": _ENTITY_TYPE,
        "state": {
            "task_id": task.task_id,
            "subject": task.subject,
            "description": task.description,
            "status": task.status.value,
            "owner": task.owner,
            "blocked_by": list(task.blocked_by),
            "worktree": task.worktree,
        },
    }


def decode_task(payload: dict[str, Any]) -> Task:
    """从经过结构校验的 JSON 对象恢复不可变任务快照。"""

    state = _get_state(payload)
    try:
        status = TaskStatus(_get_nonempty_string(state, "status"))
    except ValueError as error:
        raise ValueError(
            "任务文件字段“status”必须是 pending、in_progress 或 completed。"
        ) from error
    return Task(
        task_id=_get_nonempty_string(state, "task_id"),
        subject=_get_nonempty_string(state, "subject"),
        description=_get_string(state, "description"),
        status=status,
        owner=_get_optional_string(state, "owner"),
        blocked_by=tuple(_get_string_list(state, "blocked_by")),
        worktree=_get_optional_string(state, "worktree"),
    )


def _get_state(payload: dict[str, Any]) -> dict[str, Any]:
    """校验版本化信封，避免把其他实体误恢复为任务。"""

    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("entity_type") != _ENTITY_TYPE
        or not isinstance(payload.get("state"), dict)
    ):
        raise ValueError("任务文件结构不受支持。")
    return payload["state"]


def _get_string(payload: dict[str, Any], field_name: str) -> str:
    """读取允许为空的字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"任务文件字段“{field_name}”必须是字符串。")
    return value


def _get_nonempty_string(payload: dict[str, Any], field_name: str) -> str:
    """读取任务标识、标题和状态使用的非空字符串。"""

    value = _get_string(payload, field_name)
    if not value.strip():
        raise ValueError(f"任务文件字段“{field_name}”必须是非空字符串。")
    return value


def _get_optional_string(payload: dict[str, Any], field_name: str) -> str | None:
    """读取允许为空值但不接受空白文本的 owner 字段。"""

    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"任务文件字段“{field_name}”必须是非空字符串或空值。")
    return value


def _get_string_list(payload: dict[str, Any], field_name: str) -> list[str]:
    """读取依赖标识列表，将具体内容约束交由 Task 统一校验。"""

    value = payload.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"任务文件字段“{field_name}”必须是字符串列表。")
    return value
