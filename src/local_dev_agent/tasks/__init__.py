"""S12 跨会话任务图的领域契约。"""

from .errors import (
    CorruptedTaskFileError,
    TaskAlreadyExistsError,
    TaskBlockedError,
    TaskNotFoundError,
    TaskRepositoryError,
    TaskRuleViolationError,
    TaskStateTransitionError,
)
from .json_repository import JsonFileTaskRepository
from .ports import TaskRepository
from .rules import can_claim_task, claim_task, complete_task, unresolved_dependency_ids
from .schema import Task, TaskStatus

__all__ = [
    "Task",
    "TaskAlreadyExistsError",
    "TaskBlockedError",
    "TaskNotFoundError",
    "TaskRepository",
    "TaskRepositoryError",
    "TaskRuleViolationError",
    "TaskStateTransitionError",
    "TaskStatus",
    "CorruptedTaskFileError",
    "JsonFileTaskRepository",
    "can_claim_task",
    "claim_task",
    "complete_task",
    "unresolved_dependency_ids",
]
