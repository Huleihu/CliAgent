"""S05 待办清单的不可变领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable

from local_dev_agent.domain.state.timestamps import normalize_utc_timestamp


class TodoStatus(StrEnum):
    """待办事项在当前清单中的进度状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


def _require_nonempty_text(field_name: str, value: str) -> None:
    """拒绝无法用于展示或持久化的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


@dataclass(frozen=True, slots=True)
class TodoItem:
    """一项由 Agent 维护的平铺执行清单条目。"""

    content: str
    status: TodoStatus
    active_form: str | None = None

    def __post_init__(self) -> None:
        """确保条目能被稳定展示，并保留未来 UI 的进行时文本。"""

        _require_nonempty_text("content", self.content)
        if not isinstance(self.status, TodoStatus):
            raise ValueError("待办事项状态必须是 TodoStatus 枚举值。")
        if self.active_form is not None:
            _require_nonempty_text("active_form", self.active_form)


@dataclass(frozen=True, slots=True)
class TodoSnapshot:
    """某个待办清单在指定时间点的不可变完整视图。"""

    todo_list_id: str
    todos: tuple[TodoItem, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        """在持久化前收束清单标识、条目集合和时间表示。"""

        _require_nonempty_text("todo_list_id", self.todo_list_id)
        if not isinstance(self.todos, tuple) or not all(
            isinstance(todo, TodoItem) for todo in self.todos
        ):
            raise ValueError("待办清单必须是 TodoItem 元组。")
        object.__setattr__(
            self,
            "updated_at",
            normalize_utc_timestamp(self.updated_at, subject="待办清单"),
        )

    @classmethod
    def create(
        cls,
        *,
        todo_list_id: str,
        todos: Iterable[TodoItem] = (),
        updated_at: datetime | None = None,
    ) -> "TodoSnapshot":
        """创建快照并复制条目集合，避免调用方继续修改原集合。"""

        return cls(
            todo_list_id=todo_list_id,
            todos=tuple(todos),
            updated_at=updated_at or datetime.now(timezone.utc),
        )

    @property
    def pending_count(self) -> int:
        """返回尚未开始的待办数量。"""

        return self._count(TodoStatus.PENDING)

    @property
    def in_progress_count(self) -> int:
        """返回正在执行的待办数量。"""

        return self._count(TodoStatus.IN_PROGRESS)

    @property
    def completed_count(self) -> int:
        """返回已完成的待办数量。"""

        return self._count(TodoStatus.COMPLETED)

    def _count(self, status: TodoStatus) -> int:
        """集中统计逻辑，保证各状态计数使用同一集合快照。"""

        return sum(todo.status is status for todo in self.todos)
