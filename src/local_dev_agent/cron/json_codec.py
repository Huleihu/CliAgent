"""durable Cron 定义集合的版本化 JSON 编解码。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .expression import parse_cron_expression
from .schema import CronTask, CronTaskScope

SCHEMA_VERSION = 1
"""durable Cron 定义集合的当前 JSON 版本。"""

_ENTITY_TYPE = "cron_task_collection"


def encode_tasks(tasks: tuple[CronTask, ...]) -> dict[str, object]:
    """将 durable 定义稳定编码为一个工作区级版本化集合。"""

    if not isinstance(tasks, tuple) or not all(isinstance(task, CronTask) for task in tasks):
        raise TypeError("tasks 必须是 CronTask 元组。")
    if any(task.scope is not CronTaskScope.DURABLE for task in tasks):
        raise ValueError("durable Cron 文件不能包含 session-only 任务。")
    return {
        "schema_version": SCHEMA_VERSION,
        "entity_type": _ENTITY_TYPE,
        "tasks": [_encode_task(task) for task in tasks],
    }


def decode_tasks(payload: dict[str, Any]) -> tuple[CronTask, ...]:
    """恢复全部有效 durable 定义，跳过不安全或损坏的单条记录。"""

    raw_tasks = _get_raw_tasks(payload)
    tasks: list[CronTask] = []
    known_ids: set[str] = set()
    for raw_task in raw_tasks:
        try:
            task = _decode_task(raw_task)
        except (TypeError, ValueError):
            continue
        if task.task_id in known_ids:
            continue
        known_ids.add(task.task_id)
        tasks.append(task)
    return tuple(sorted(tasks, key=lambda task: (task.created_at, task.task_id)))


def _encode_task(task: CronTask) -> dict[str, object]:
    """编码一个已验证 durable 快照，不写入不适用的 Session 归属。"""

    return {
        "task_id": task.task_id,
        "cron": task.cron,
        "prompt": task.prompt,
        "recurring": task.recurring,
        "scope": task.scope.value,
        "created_at": task.created_at.isoformat(),
        "last_enqueued_minute": (
            task.last_enqueued_minute.isoformat()
            if task.last_enqueued_minute is not None
            else None
        ),
    }


def _get_raw_tasks(payload: dict[str, Any]) -> list[object]:
    """校验集合信封，避免把其他持久化实体误当作 Cron 定义。"""

    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("entity_type") != _ENTITY_TYPE
        or not isinstance(payload.get("tasks"), list)
    ):
        raise ValueError("Cron 任务文件结构不受支持。")
    return payload["tasks"]


def _decode_task(raw_task: object) -> CronTask:
    """恢复并再次解析单条 durable 定义，保证 Scheduler 只看见安全表达式。"""

    if not isinstance(raw_task, dict):
        raise ValueError("Cron 任务条目必须是对象。")
    scope = CronTaskScope(_get_nonempty_string(raw_task, "scope"))
    if scope is not CronTaskScope.DURABLE:
        raise ValueError("durable Cron 文件不能包含 session-only 任务。")
    parsed_expression = parse_cron_expression(_get_nonempty_string(raw_task, "cron"))
    return CronTask(
        task_id=_get_nonempty_string(raw_task, "task_id"),
        cron=parsed_expression.source,
        prompt=_get_nonempty_string(raw_task, "prompt"),
        recurring=_get_boolean(raw_task, "recurring"),
        scope=scope,
        created_at=_get_datetime(raw_task, "created_at"),
        last_enqueued_minute=_get_optional_datetime(
            raw_task,
            "last_enqueued_minute",
        ),
    )


def _get_nonempty_string(payload: dict[str, object], field_name: str) -> str:
    """读取标识、表达式和提示使用的非空字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Cron 任务文件字段“{field_name}”必须是非空字符串。")
    return value


def _get_boolean(payload: dict[str, object], field_name: str) -> bool:
    """读取严格布尔值，避免 JSON 数字伪装为生命周期开关。"""

    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"Cron 任务文件字段“{field_name}”必须是布尔值。")
    return value


def _get_datetime(payload: dict[str, object], field_name: str) -> datetime:
    """读取带时区 ISO 时间，具体 UTC 规范化交由领域快照完成。"""

    value = _get_nonempty_string(payload, field_name)
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Cron 任务文件字段“{field_name}”必须是 ISO 时间。") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"Cron 任务文件字段“{field_name}”必须包含时区。")
    return timestamp


def _get_optional_datetime(payload: dict[str, object], field_name: str) -> datetime | None:
    """读取可空的最近入队分钟；非空时沿用同一时间校验。"""

    if payload.get(field_name) is None:
        return None
    return _get_datetime(payload, field_name)
