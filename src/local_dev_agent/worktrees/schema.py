"""S18 工作树隔离的不可变领域契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import InvalidWorktreeNameError


_WORKTREE_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


class WorktreeEventType(StrEnum):
    """可追加记录的工作树生命周期事实。"""

    CREATE = "create"
    REMOVE = "remove"
    KEEP = "keep"


def validate_worktree_name(name: str) -> str:
    """校验工作树名称，阻断路径穿越和分隔符进入后续文件系统适配器。"""

    if not isinstance(name, str) or not name:
        raise InvalidWorktreeNameError(name=name, reason="名称不能为空")
    if name in {".", ".."}:
        raise InvalidWorktreeNameError(name=name, reason="名称不能是“.”或“..”")
    if "/" in name or "\\" in name:
        raise InvalidWorktreeNameError(name=name, reason="名称不能包含路径分隔符")
    if _WORKTREE_NAME_PATTERN.fullmatch(name) is None:
        raise InvalidWorktreeNameError(
            name=name,
            reason="仅允许 1 至 64 个字母、数字、点、下划线或连字符",
        )
    return name


def worktree_branch_name(name: str) -> str:
    """由已校验名称导出受控分支名，避免适配器自行拼接不可信输入。"""

    return f"wt/{validate_worktree_name(name)}"


@dataclass(frozen=True, slots=True)
class Worktree:
    """Git 生命周期端口确认存在或已删除的工作树事实。"""

    name: str
    directory: str
    branch: str
    base_commit: str

    def __post_init__(self) -> None:
        """收束由适配器返回的可审计工作树标识和展示信息。"""

        validate_worktree_name(self.name)
        if not isinstance(self.directory, str) or not self.directory.strip():
            raise ValueError("工作树目录必须是非空字符串。")
        if not isinstance(self.branch, str) or not self.branch.strip():
            raise ValueError("工作树分支必须是非空字符串。")
        if not isinstance(self.base_commit, str) or not self.base_commit.strip():
            raise ValueError("工作树基准提交必须是非空字符串。")


@dataclass(frozen=True, slots=True)
class WorktreeChanges:
    """删除前由 Git 适配器取得的工作树改动事实。"""

    uncommitted_file_count: int
    unpushed_commit_count: int

    def __post_init__(self) -> None:
        """拒绝未知或负数计数，避免安全删除误把不确定性当作干净。"""

        if (
            not isinstance(self.uncommitted_file_count, int)
            or self.uncommitted_file_count < 0
            or not isinstance(self.unpushed_commit_count, int)
            or self.unpushed_commit_count < 0
        ):
            raise ValueError("工作树改动计数必须是非负整数。")

    @property
    def is_clean(self) -> bool:
        """仅当未提交改动和未推送提交都为零时允许默认删除。"""

        return self.uncommitted_file_count == 0 and self.unpushed_commit_count == 0


@dataclass(frozen=True, slots=True)
class WorktreeLifecycleEvent:
    """仅在对应生命周期事实成功后追加的审计事件。"""

    event_type: WorktreeEventType
    operation_id: str
    worktree: Worktree
    task_id: str | None
    occurred_at: datetime

    def __post_init__(self) -> None:
        """保证事件可按幂等键、工作树和可选任务关系稳定追溯。"""

        if not isinstance(self.event_type, WorktreeEventType):
            raise ValueError("工作树事件类型必须是 WorktreeEventType 枚举值。")
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("工作树操作标识必须是非空字符串。")
        if not isinstance(self.worktree, Worktree):
            raise TypeError("工作树事件必须携带 Worktree 对象。")
        if self.task_id is not None and (
            not isinstance(self.task_id, str) or not self.task_id.strip()
        ):
            raise ValueError("任务标识必须是非空字符串或空值。")
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("工作树事件发生时间必须是 datetime 对象。")


@dataclass(frozen=True, slots=True)
class WorktreeOperationResult:
    """工作树应用用例的成功结果，并标识是否由同一操作重放得到。"""

    event: WorktreeLifecycleEvent
    replayed: bool = False

    def __post_init__(self) -> None:
        """冻结成功结果，避免工具层篡改事件事实或重放标识。"""

        if not isinstance(self.event, WorktreeLifecycleEvent):
            raise TypeError("工作树操作结果必须携带生命周期事件。")
        if not isinstance(self.replayed, bool):
            raise TypeError("工作树操作结果的重放标识必须是布尔值。")
