"""任务图领域规则产生的可诊断错误。"""

from __future__ import annotations

from .schema import TaskStatus


class TaskRuleViolationError(ValueError):
    """任务依赖或状态机规则未满足时的统一基类。"""


class TaskBlockedError(TaskRuleViolationError):
    """任务仍存在缺失或未完成的前置依赖时抛出。"""

    def __init__(self, *, task_id: str, blocked_by: tuple[str, ...]) -> None:
        super().__init__(
            f"任务“{task_id}”仍被以下依赖阻塞：{'、'.join(blocked_by)}。"
        )
        self.task_id = task_id
        self.blocked_by = blocked_by


class TaskStateTransitionError(TaskRuleViolationError):
    """任务未处于允许执行指定动作的状态时抛出。"""

    def __init__(self, *, task_id: str, action: str, status: TaskStatus) -> None:
        super().__init__(
            f"任务“{task_id}”当前状态为“{status.value}”，不能执行“{action}”。"
        )
        self.task_id = task_id
        self.action = action
        self.status = status
