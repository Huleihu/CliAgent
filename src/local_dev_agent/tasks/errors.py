"""任务图领域规则产生的可诊断错误。"""

from __future__ import annotations

from pathlib import Path

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


class TaskWorktreeAlreadyBoundError(TaskRuleViolationError):
    """拒绝将已绑定其他工作树的任务改绑到新工作树。"""

    def __init__(
        self,
        *,
        task_id: str,
        current_worktree: str,
        requested_worktree: str,
    ) -> None:
        super().__init__(
            f"任务“{task_id}”已绑定工作树“{current_worktree}”，"
            f"不能改绑为“{requested_worktree}”。"
        )
        self.task_id = task_id
        self.current_worktree = current_worktree
        self.requested_worktree = requested_worktree


class TaskRepositoryError(ValueError):
    """任务仓储适配器产生的基础设施错误。"""


class CorruptedTaskFileError(TaskRepositoryError):
    """任务文件无法解析、标识不匹配或结构不受支持时抛出。"""

    def __init__(self, *, path: Path) -> None:
        super().__init__(f"任务文件“{path}”已损坏或格式不受支持。")
        self.path = path


class TaskAlreadyExistsError(TaskRepositoryError):
    """新增任务时发现同一稳定标识已存在时抛出。"""

    def __init__(self, *, task_id: str) -> None:
        super().__init__(f"任务“{task_id}”已存在，不能重复创建。")
        self.task_id = task_id


class TaskNotFoundError(TaskRepositoryError):
    """替换尚不存在的任务快照时抛出。"""

    def __init__(self, *, task_id: str) -> None:
        super().__init__(f"任务“{task_id}”不存在。")
        self.task_id = task_id
