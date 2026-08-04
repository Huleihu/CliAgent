"""S18 工作树生命周期、事件与时钟的稳定端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .schema import Worktree, WorktreeChanges, WorktreeLifecycleEvent


class WorktreeLifecycleGateway(Protocol):
    """隔离 Git、子进程和文件系统的工作树生命周期端口。"""

    def create(self, *, name: str) -> Worktree:
        """真实创建工作树及受控分支，成功后返回其事实。"""

    def inspect_changes(self, *, name: str) -> WorktreeChanges:
        """读取删除前的未提交改动和未推送提交计数。"""

    def remove(self, *, name: str, discard_changes: bool) -> Worktree:
        """真实移除工作树并按需要放弃改动，成功后返回被移除的事实。"""

    def keep(self, *, name: str) -> Worktree:
        """确认工作树仍存在且可供人工评审，返回其事实。"""


class WorktreeEventJournal(Protocol):
    """提供按操作标识重放和追加审计事件的端口。"""

    def find_by_operation_id(self, operation_id: str) -> WorktreeLifecycleEvent | None:
        """读取同一幂等键已追加的生命周期事件。"""

    def append(self, event: WorktreeLifecycleEvent) -> None:
        """追加一个不可变生命周期事件。"""


class WorktreeClock(Protocol):
    """为审计事件提供可替换、可测试的时间来源。"""

    def now(self) -> datetime:
        """返回当前带时区或无时区的 datetime，由具体组合根统一约定。"""
