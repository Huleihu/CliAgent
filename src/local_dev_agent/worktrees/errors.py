"""S18 工作树领域产生的可诊断错误。"""

from __future__ import annotations

class WorktreeError(ValueError):
    """工作树领域错误的统一基类。"""


class InvalidWorktreeNameError(WorktreeError):
    """工作树名称不满足受控单目录名称规则时抛出。"""

    def __init__(self, *, name: object, reason: str) -> None:
        super().__init__(f"工作树名称“{name}”无效：{reason}。")
        self.name = name
        self.reason = reason


class WorktreeUnsafeToRemoveError(WorktreeError):
    """默认删除发现未提交改动或未推送提交时抛出。"""

    def __init__(
        self,
        *,
        name: str,
        uncommitted_file_count: int,
        unpushed_commit_count: int,
    ) -> None:
        super().__init__(
            f"工作树“{name}”存在 {uncommitted_file_count} 个未提交改动和"
            f"{unpushed_commit_count} 个未推送提交；"
            "如确认放弃，请显式设置 discard_changes=true。"
        )
        self.name = name
        self.uncommitted_file_count = uncommitted_file_count
        self.unpushed_commit_count = unpushed_commit_count


class WorktreeOperationConflictError(WorktreeError):
    """同一幂等操作标识被用于不同工作树生命周期请求时抛出。"""

    def __init__(
        self,
        *,
        operation_id: str,
        requested_event_type: object,
        recorded_event_type: object,
    ) -> None:
        super().__init__(
            f"工作树操作标识“{operation_id}”已记录为“{recorded_event_type}”，"
            f"不能重用于“{requested_event_type}”。"
        )
        self.operation_id = operation_id
        self.requested_event_type = requested_event_type
        self.recorded_event_type = recorded_event_type


class GitWorktreeLifecycleError(WorktreeError):
    """Git 命令无法确认工作树生命周期事实时抛出。"""

    def __init__(self, *, operation: str, detail: str) -> None:
        super().__init__(f"Git 工作树操作“{operation}”失败：{detail}。")
        self.operation = operation
        self.detail = detail


class WorktreeEventJournalError(WorktreeError):
    """工作树事件日志无法安全读取或追加时抛出。"""

    def __init__(self, *, detail: str) -> None:
        super().__init__(f"工作树事件日志失败：{detail}。")
        self.detail = detail
