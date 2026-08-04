"""协调任务绑定、工作树生命周期与审计事件的应用服务。"""

from __future__ import annotations

from local_dev_agent.tasks import (
    TaskSnapshotReader,
    TaskWorktreeAlreadyBoundError,
    TaskWorktreeBinder,
)

from .errors import WorktreeOperationConflictError, WorktreeUnsafeToRemoveError
from .ports import WorktreeClock, WorktreeEventJournal, WorktreeLifecycleGateway
from .schema import (
    WorktreeEventType,
    WorktreeLifecycleEvent,
    WorktreeOperationResult,
    Worktree,
    validate_worktree_name,
)


class WorktreeService:
    """只编排事实顺序；Git、JSONL 和文件系统均由适配器实现。"""

    def __init__(
        self,
        lifecycle_gateway: WorktreeLifecycleGateway,
        event_journal: WorktreeEventJournal,
        clock: WorktreeClock,
        task_reader: TaskSnapshotReader,
        task_binder: TaskWorktreeBinder,
    ) -> None:
        self._require_callable_methods(
            lifecycle_gateway,
            ("create", "inspect_changes", "remove", "keep"),
            "工作树生命周期网关",
        )
        self._require_callable_methods(
            event_journal,
            ("find_by_operation_id", "append"),
            "工作树事件日志",
        )
        self._require_callable_methods(clock, ("now",), "工作树时钟")
        self._require_callable_methods(task_reader, ("get_task",), "任务读取器")
        self._require_callable_methods(task_binder, ("bind_worktree",), "任务工作树绑定器")
        self._lifecycle_gateway = lifecycle_gateway
        self._event_journal = event_journal
        self._clock = clock
        self._task_reader = task_reader
        self._task_binder = task_binder

    def create_worktree(
        self,
        *,
        name: str,
        operation_id: str,
        task_id: str | None = None,
    ) -> WorktreeOperationResult:
        """创建后再绑定任务，且仅在两项事实成功后追加 create 事件。"""

        validated_name = validate_worktree_name(name)
        normalized_task_id = self._normalize_optional_task_id(task_id)
        replayed = self._replayed_result(
            operation_id=operation_id,
            event_type=WorktreeEventType.CREATE,
            name=validated_name,
            task_id=normalized_task_id,
        )
        if replayed is not None:
            return replayed
        if normalized_task_id is not None:
            task = self._task_reader.get_task(normalized_task_id)
            if task.worktree is not None and task.worktree != validated_name:
                raise TaskWorktreeAlreadyBoundError(
                    task_id=task.task_id,
                    current_worktree=task.worktree,
                    requested_worktree=validated_name,
                )
        worktree = self._lifecycle_gateway.create(name=validated_name)
        if normalized_task_id is not None:
            self._task_binder.bind_worktree(
                task_id=normalized_task_id,
                worktree=validated_name,
            )
        return self._append_result(
            event_type=WorktreeEventType.CREATE,
            operation_id=operation_id,
            worktree=worktree,
            task_id=normalized_task_id,
        )

    def remove_worktree(
        self,
        *,
        name: str,
        operation_id: str,
        discard_changes: bool = False,
    ) -> WorktreeOperationResult:
        """默认拒绝脏工作树，仅显式放弃改动时允许强制删除。"""

        validated_name = validate_worktree_name(name)
        if not isinstance(discard_changes, bool):
            raise ValueError("discard_changes 必须是布尔值。")
        replayed = self._replayed_result(
            operation_id=operation_id,
            event_type=WorktreeEventType.REMOVE,
            name=validated_name,
            task_id=None,
        )
        if replayed is not None:
            return replayed
        if not discard_changes:
            changes = self._lifecycle_gateway.inspect_changes(name=validated_name)
            if not changes.is_clean:
                raise WorktreeUnsafeToRemoveError(
                    name=validated_name,
                    uncommitted_file_count=changes.uncommitted_file_count,
                    unpushed_commit_count=changes.unpushed_commit_count,
                )
        worktree = self._lifecycle_gateway.remove(
            name=validated_name,
            discard_changes=discard_changes,
        )
        return self._append_result(
            event_type=WorktreeEventType.REMOVE,
            operation_id=operation_id,
            worktree=worktree,
            task_id=None,
        )

    def keep_worktree(
        self,
        *,
        name: str,
        operation_id: str,
    ) -> WorktreeOperationResult:
        """确认保留事实后追加 keep 事件，不触碰任务图。"""

        validated_name = validate_worktree_name(name)
        replayed = self._replayed_result(
            operation_id=operation_id,
            event_type=WorktreeEventType.KEEP,
            name=validated_name,
            task_id=None,
        )
        if replayed is not None:
            return replayed
        worktree = self._lifecycle_gateway.keep(name=validated_name)
        return self._append_result(
            event_type=WorktreeEventType.KEEP,
            operation_id=operation_id,
            worktree=worktree,
            task_id=None,
        )

    def _replayed_result(
        self,
        *,
        operation_id: str,
        event_type: WorktreeEventType,
        name: str,
        task_id: str | None,
    ) -> WorktreeOperationResult | None:
        """将同一操作标识的成功重试折叠为同一事件，而非再次调用 Git。"""

        self._require_operation_id(operation_id)
        event = self._event_journal.find_by_operation_id(operation_id)
        if event is None:
            return None
        if event.event_type is not event_type:
            raise WorktreeOperationConflictError(
                operation_id=operation_id,
                requested_event_type=event_type,
                recorded_event_type=event.event_type,
            )
        if event.worktree.name != name or event.task_id != task_id:
            raise ValueError("工作树操作标识不能重用于不同的工作树或任务。")
        return WorktreeOperationResult(event=event, replayed=True)

    def _append_result(
        self,
        *,
        event_type: WorktreeEventType,
        operation_id: str,
        worktree: Worktree,
        task_id: str | None,
    ) -> WorktreeOperationResult:
        """在生命周期端口已确认成功后，构造并追加唯一审计事件。"""

        event = WorktreeLifecycleEvent(
            event_type=event_type,
            operation_id=operation_id,
            worktree=worktree,
            task_id=task_id,
            occurred_at=self._clock.now(),
        )
        self._event_journal.append(event)
        return WorktreeOperationResult(event=event)

    @staticmethod
    def _normalize_optional_task_id(task_id: str | None) -> str | None:
        """拒绝把空字符串误解为未绑定任务，保持事件语义明确。"""

        if task_id is None:
            return None
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("任务标识必须是非空字符串或空值。")
        return task_id

    @staticmethod
    def _require_operation_id(operation_id: str) -> None:
        """要求调用方提供稳定幂等键，后续 Lead 工具会使用 call_id。"""

        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("工作树操作标识必须是非空字符串。")

    @staticmethod
    def _require_callable_methods(
        value: object,
        method_names: tuple[str, ...],
        port_name: str,
    ) -> None:
        """在组合根装配错误时尽早报告缺失端口，而非运行到半途。"""

        if not all(callable(getattr(value, method_name, None)) for method_name in method_names):
            raise TypeError(f"{port_name}必须提供所需方法。")
