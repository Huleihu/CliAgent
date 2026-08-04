"""跨会话任务图持久化的稳定端口。"""

from collections.abc import Sequence
from typing import Protocol

from .schema import Task


class TaskRepository(Protocol):
    """保存和查询单个任务快照，不包含 JSON、锁或工具协议。"""

    def add(self, task: Task) -> Task:
        """新增一个任务；同标识任务的冲突由具体仓储报告。"""

    def get(self, task_id: str) -> Task | None:
        """按标识读取任务；不存在时返回空值。"""

    def list(self) -> Sequence[Task]:
        """返回稳定顺序的任务快照序列。"""

    def replace(self, task: Task) -> Task:
        """以新的完整快照替换已有任务。"""

    def compare_and_replace(self, *, expected: Task, replacement: Task) -> bool:
        """仅当当前快照仍等于 expected 时替换，成功时返回真。"""


class AutonomousTaskBoard(Protocol):
    """供自主成员发现并安全认领任务的只需端口。"""

    def list_claimable_tasks(self) -> tuple[Task, ...]:
        """返回当前依赖已满足且尚未认领的稳定候选快照。"""

    def claim_next_task(self, *, owner: str) -> Task | None:
        """按稳定候选顺序尝试认领一项任务，无可认领任务时返回空值。"""


class TaskIdGenerator(Protocol):
    """为新建任务提供可替换且无需仓储参与的稳定标识。"""

    def new_task_id(self) -> str:
        """生成一个尚待仓储持久化的任务标识。"""
