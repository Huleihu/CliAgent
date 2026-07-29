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
