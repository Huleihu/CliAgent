"""S12 跨会话任务图的领域契约。"""

from .errors import TaskBlockedError, TaskRuleViolationError, TaskStateTransitionError
from .ports import TaskRepository
from .rules import can_claim_task, claim_task, complete_task, unresolved_dependency_ids
from .schema import Task, TaskStatus

__all__ = [
    "Task",
    "TaskBlockedError",
    "TaskRepository",
    "TaskRuleViolationError",
    "TaskStateTransitionError",
    "TaskStatus",
    "can_claim_task",
    "claim_task",
    "complete_task",
    "unresolved_dependency_ids",
]
