"""协调任务仓储与纯领域规则的应用服务。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .errors import TaskNotFoundError
from .ports import TaskIdGenerator, TaskRepository
from .rules import can_claim_task, claim_task as apply_claim, complete_task as apply_complete
from .schema import Task, TaskStatus


@dataclass(frozen=True, slots=True)
class TaskCompletion:
    """完成任务后的持久化快照与本次新解锁的下游任务。"""

    task: Task
    unblocked_tasks: tuple[Task, ...]

    def __post_init__(self) -> None:
        """冻结完成结果，防止工具层在返回前改写任务事实。"""

        if not isinstance(self.task, Task):
            raise TypeError("task 必须是 Task 对象。")
        if not isinstance(self.unblocked_tasks, tuple) or not all(
            isinstance(task, Task) for task in self.unblocked_tasks
        ):
            raise TypeError("unblocked_tasks 必须是 Task 元组。")


class TaskApplicationService(Protocol):
    """任务工具依赖的应用用例端口，不暴露仓储和标识生成细节。"""

    def create_task(
        self,
        *,
        subject: str,
        description: str = "",
        blocked_by: Iterable[str] = (),
    ) -> Task:
        """创建并持久化待认领任务。"""

    def list_tasks(self) -> tuple[Task, ...]:
        """返回当前任务图的稳定快照。"""

    def get_task(self, task_id: str) -> Task:
        """读取指定任务。"""

    def claim_task(self, *, task_id: str, owner: str) -> Task:
        """认领指定任务。"""

    def complete_task(self, *, task_id: str) -> TaskCompletion:
        """完成指定任务并返回本次解锁结果。"""


class TaskService:
    """提供创建、查询、认领和完成任务的无界面应用用例。"""

    def __init__(self, repository: TaskRepository, id_generator: TaskIdGenerator) -> None:
        if not all(
            callable(getattr(repository, method_name, None))
            for method_name in ("add", "get", "list", "replace")
        ):
            raise TypeError("任务仓储必须提供 add、get、list 和 replace 方法。")
        if not callable(getattr(id_generator, "new_task_id", None)):
            raise TypeError("任务标识生成器必须提供 new_task_id 方法。")
        self._repository = repository
        self._id_generator = id_generator

    def create_task(
        self,
        *,
        subject: str,
        description: str = "",
        blocked_by: Iterable[str] = (),
    ) -> Task:
        """生成标识、创建待认领快照并交由仓储新增。"""

        task = Task.create(
            task_id=self._id_generator.new_task_id(),
            subject=subject,
            description=description,
            blocked_by=blocked_by,
        )
        return self._repository.add(task)

    def list_tasks(self) -> tuple[Task, ...]:
        """读取并冻结当前任务列表，避免调用方依赖仓储的可变返回值。"""

        tasks = tuple(self._repository.list())
        if not all(isinstance(task, Task) for task in tasks):
            raise TypeError("任务仓储必须只返回 Task 对象。")
        return tasks

    def get_task(self, task_id: str) -> Task:
        """读取任务，不存在时以稳定的任务领域错误拒绝。"""

        task = self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id=task_id)
        if not isinstance(task, Task):
            raise TypeError("任务仓储必须返回 Task 对象或空值。")
        return task

    def claim_task(self, *, task_id: str, owner: str) -> Task:
        """读取依赖快照、应用认领规则并持久化新的任务状态。"""

        task = self.get_task(task_id)
        claimed_task = apply_claim(
            task,
            owner=owner,
            dependencies=self._dependency_snapshot(task),
        )
        return self._repository.replace(claimed_task)

    def complete_task(self, *, task_id: str) -> TaskCompletion:
        """完成任务后重查待认领下游任务，并返回本次新解锁集合。"""

        task = self.get_task(task_id)
        claimable_task_ids_before = frozenset(
            candidate.task_id for candidate in self._claimable_pending_tasks()
        )
        completed_task = self._repository.replace(apply_complete(task))
        unblocked_tasks = tuple(
            candidate
            for candidate in self._claimable_pending_tasks()
            if candidate.task_id not in claimable_task_ids_before
        )
        return TaskCompletion(
            task=completed_task,
            unblocked_tasks=unblocked_tasks,
        )

    def _claimable_pending_tasks(self) -> tuple[Task, ...]:
        """返回当前可认领且声明过依赖的任务，用于比较解锁前后状态。"""

        return tuple(
            candidate
            for candidate in self.list_tasks()
            if candidate.status is TaskStatus.PENDING
            and candidate.blocked_by
            and can_claim_task(
                candidate,
                self._dependency_snapshot(candidate),
            )
        )

    def _dependency_snapshot(self, task: Task) -> dict[str, Task]:
        """按依赖标识读取实际任务；缺失条目保留给领域规则判定为阻塞。"""

        dependencies: dict[str, Task] = {}
        for dependency_id in task.blocked_by:
            dependency = self._repository.get(dependency_id)
            if dependency is not None:
                if not isinstance(dependency, Task):
                    raise TypeError("任务仓储必须返回 Task 对象或空值。")
                dependencies[dependency_id] = dependency
        return dependencies
