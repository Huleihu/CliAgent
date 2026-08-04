"""任务依赖与状态转换的纯领域规则。"""

from __future__ import annotations

from collections.abc import Mapping

from .errors import (
    TaskBlockedError,
    TaskStateTransitionError,
    TaskWorktreeAlreadyBoundError,
)
from .schema import Task, TaskStatus


def unresolved_dependency_ids(
    task: Task,
    dependencies: Mapping[str, Task],
) -> tuple[str, ...]:
    """返回缺失或尚未完成的依赖标识，保持任务声明的稳定顺序。"""

    _require_task(task)
    _require_dependencies(dependencies)
    return tuple(
        dependency_id
        for dependency_id in task.blocked_by
        if (
            (dependency := dependencies.get(dependency_id)) is None
            or dependency.status is not TaskStatus.COMPLETED
        )
    )


def can_claim_task(task: Task, dependencies: Mapping[str, Task]) -> bool:
    """仅当任务待认领且全部依赖已完成时允许认领。"""

    _require_task(task)
    return (
        task.status is TaskStatus.PENDING
        and not unresolved_dependency_ids(task, dependencies)
    )


def claim_task(
    task: Task,
    *,
    owner: str,
    dependencies: Mapping[str, Task],
) -> Task:
    """认领待认领且未被阻塞的任务，并返回新的不可变快照。"""

    _require_task(task)
    if task.status is not TaskStatus.PENDING:
        raise TaskStateTransitionError(
            task_id=task.task_id,
            action="认领",
            status=task.status,
        )
    unresolved_ids = unresolved_dependency_ids(task, dependencies)
    if unresolved_ids:
        raise TaskBlockedError(task_id=task.task_id, blocked_by=unresolved_ids)
    return Task(
        task_id=task.task_id,
        subject=task.subject,
        description=task.description,
        status=TaskStatus.IN_PROGRESS,
        owner=owner,
        blocked_by=task.blocked_by,
        worktree=task.worktree,
    )


def complete_task(task: Task) -> Task:
    """完成已认领任务，并保留其负责人和依赖声明用于追溯。"""

    _require_task(task)
    if task.status is not TaskStatus.IN_PROGRESS:
        raise TaskStateTransitionError(
            task_id=task.task_id,
            action="完成",
            status=task.status,
        )
    return Task(
        task_id=task.task_id,
        subject=task.subject,
        description=task.description,
        status=TaskStatus.COMPLETED,
        owner=task.owner,
        blocked_by=task.blocked_by,
        worktree=task.worktree,
    )


def bind_worktree(task: Task, *, worktree: str) -> Task:
    """绑定工作树名称且保留任务图状态；同名重试返回原快照。"""

    _require_task(task)
    if task.worktree == worktree:
        return task
    if task.worktree is not None:
        raise TaskWorktreeAlreadyBoundError(
            task_id=task.task_id,
            current_worktree=task.worktree,
            requested_worktree=worktree,
        )
    return Task(
        task_id=task.task_id,
        subject=task.subject,
        description=task.description,
        status=task.status,
        owner=task.owner,
        blocked_by=task.blocked_by,
        worktree=worktree,
    )


def _require_task(task: Task) -> None:
    """尽早拒绝错误类型，避免规则函数产生不清晰的属性错误。"""

    if not isinstance(task, Task):
        raise TypeError("task 必须是 Task 对象。")


def _require_dependencies(dependencies: Mapping[str, Task]) -> None:
    """确认依赖快照是以任务标识索引的映射。"""

    if not isinstance(dependencies, Mapping) or not all(
        isinstance(task_id, str) and task_id.strip() and isinstance(task, Task)
        for task_id, task in dependencies.items()
    ):
        raise TypeError("dependencies 必须是由非空任务标识映射到 Task 的对象。")
