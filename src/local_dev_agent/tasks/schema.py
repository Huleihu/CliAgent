"""S12 跨会话任务图的不可变领域模型。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    """任务在可认领生命周期中的稳定状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


def _require_nonempty_text(field_name: str, value: str) -> None:
    """拒绝无法标识、展示或归属任务的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


def _copy_dependency_ids(blocked_by: Iterable[str]) -> tuple[str, ...]:
    """复制依赖标识，隔离调用方后续对可变集合的修改。"""

    if isinstance(blocked_by, str) or not isinstance(blocked_by, Iterable):
        raise ValueError("字段“blocked_by”必须是非空字符串元组。")
    return tuple(blocked_by)


@dataclass(frozen=True, slots=True)
class Task:
    """一个可跨会话查询、认领和完成的任务图节点。"""

    task_id: str
    subject: str
    description: str
    status: TaskStatus
    owner: str | None
    blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """收束任务字段与生命周期不变量，不在此处遍历任务图。"""

        _require_nonempty_text("task_id", self.task_id)
        _require_nonempty_text("subject", self.subject)
        if not isinstance(self.description, str):
            raise ValueError("字段“description”必须是字符串。")
        if not isinstance(self.status, TaskStatus):
            raise ValueError("任务状态必须是 TaskStatus 枚举值。")
        if self.owner is not None:
            _require_nonempty_text("owner", self.owner)
        if not isinstance(self.blocked_by, tuple) or not all(
            isinstance(task_id, str) and task_id.strip() for task_id in self.blocked_by
        ):
            raise ValueError("字段“blocked_by”必须是非空字符串元组。")
        if len(set(self.blocked_by)) != len(self.blocked_by):
            raise ValueError("字段“blocked_by”不能包含重复任务标识。")
        if self.status is TaskStatus.PENDING and self.owner is not None:
            raise ValueError("待认领任务不能设置 owner。")
        if self.status is not TaskStatus.PENDING and self.owner is None:
            raise ValueError("已认领或已完成任务必须设置 owner。")

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        subject: str,
        description: str = "",
        blocked_by: Iterable[str] = (),
    ) -> "Task":
        """创建待认领任务并复制依赖集合，避免暴露可变内部状态。"""

        return cls(
            task_id=task_id,
            subject=subject,
            description=description,
            status=TaskStatus.PENDING,
            owner=None,
            blocked_by=_copy_dependency_ids(blocked_by),
        )
