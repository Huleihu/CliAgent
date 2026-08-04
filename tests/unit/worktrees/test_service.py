from datetime import datetime

import pytest

from local_dev_agent.tasks import Task, TaskWorktreeAlreadyBoundError, bind_worktree
from local_dev_agent.worktrees import (
    Worktree,
    WorktreeChanges,
    WorktreeError,
    WorktreeLifecycleEvent,
    WorktreeOperationConflictError,
    WorktreeService,
    WorktreeUnsafeToRemoveError,
)


class FakeWorktreeLifecycleGateway:
    """以调用记录替代 Git，验证应用服务决定正确的生命周期顺序。"""

    def __init__(
        self,
        *,
        changes: WorktreeChanges = WorktreeChanges(0, 0),
        create_error: Exception | None = None,
        remove_error: Exception | None = None,
    ) -> None:
        self.changes = changes
        self.create_error = create_error
        self.remove_error = remove_error
        self.calls: list[tuple[str, str, bool | None]] = []

    @staticmethod
    def _worktree(name: str) -> Worktree:
        return Worktree(
            name=name,
            directory=f".worktrees/{name}",
            branch=f"wt/{name}",
        )

    def create(self, *, name: str) -> Worktree:
        self.calls.append(("create", name, None))
        if self.create_error is not None:
            raise self.create_error
        return self._worktree(name)

    def inspect_changes(self, *, name: str) -> WorktreeChanges:
        self.calls.append(("inspect_changes", name, None))
        return self.changes

    def remove(self, *, name: str, discard_changes: bool) -> Worktree:
        self.calls.append(("remove", name, discard_changes))
        if self.remove_error is not None:
            raise self.remove_error
        return self._worktree(name)

    def keep(self, *, name: str) -> Worktree:
        self.calls.append(("keep", name, None))
        return self._worktree(name)


class InMemoryWorktreeEventJournal:
    """用追加列表模拟审计日志，并按操作标识提供重放读取。"""

    def __init__(self) -> None:
        self.events: list[WorktreeLifecycleEvent] = []

    def find_by_operation_id(self, operation_id: str) -> WorktreeLifecycleEvent | None:
        return next((event for event in self.events if event.operation_id == operation_id), None)

    def append(self, event: WorktreeLifecycleEvent) -> None:
        self.events.append(event)


class FixedClock:
    """提供固定时间，使事件断言不依赖系统时钟。"""

    def now(self) -> datetime:
        return datetime(2026, 8, 4, 12, 0, 0)


class InMemoryTaskBindings:
    """用 S12 纯绑定规则模拟任务读取与 CAS 之后的绑定结果。"""

    def __init__(self, task: Task) -> None:
        self.task = task
        self.bind_calls: list[tuple[str, str]] = []

    def get_task(self, task_id: str) -> Task:
        assert task_id == self.task.task_id
        return self.task

    def bind_worktree(self, *, task_id: str, worktree: str) -> Task:
        assert task_id == self.task.task_id
        self.bind_calls.append((task_id, worktree))
        self.task = bind_worktree(self.task, worktree=worktree)
        return self.task


def _service(
    *,
    task: Task | None = None,
    changes: WorktreeChanges = WorktreeChanges(0, 0),
    create_error: Exception | None = None,
    remove_error: Exception | None = None,
) -> tuple[WorktreeService, FakeWorktreeLifecycleGateway, InMemoryWorktreeEventJournal, InMemoryTaskBindings]:
    bindings = InMemoryTaskBindings(
        task if task is not None else Task.create(task_id="task-api", subject="实现 API。")
    )
    gateway = FakeWorktreeLifecycleGateway(
        changes=changes,
        create_error=create_error,
        remove_error=remove_error,
    )
    journal = InMemoryWorktreeEventJournal()
    return (
        WorktreeService(gateway, journal, FixedClock(), bindings, bindings),
        gateway,
        journal,
        bindings,
    )


def test_create_worktree_binds_only_the_task_worktree_and_then_appends_an_event() -> None:
    task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        blocked_by=("task-schema",),
    )
    service, gateway, journal, bindings = _service(task=task)

    result = service.create_worktree(
        name="api-login",
        task_id="task-api",
        operation_id="call-create-1",
    )

    assert result.replayed is False
    assert result.event.task_id == "task-api"
    assert result.event.worktree.branch == "wt/api-login"
    assert gateway.calls == [("create", "api-login", None)]
    assert bindings.bind_calls == [("task-api", "api-login")]
    assert bindings.task.worktree == "api-login"
    assert bindings.task.status == task.status
    assert bindings.task.owner == task.owner
    assert bindings.task.blocked_by == task.blocked_by
    assert journal.events == [result.event]


def test_create_worktree_replays_a_successful_operation_without_calling_lifecycle_or_binding_again() -> None:
    service, gateway, journal, bindings = _service()

    first = service.create_worktree(
        name="api-login",
        task_id="task-api",
        operation_id="call-create-1",
    )
    replayed = service.create_worktree(
        name="api-login",
        task_id="task-api",
        operation_id="call-create-1",
    )

    assert first.replayed is False
    assert replayed.replayed is True
    assert replayed.event == first.event
    assert gateway.calls == [("create", "api-login", None)]
    assert bindings.bind_calls == [("task-api", "api-login")]
    assert journal.events == [first.event]


def test_create_worktree_does_not_bind_or_append_an_event_when_git_creation_fails() -> None:
    service, gateway, journal, bindings = _service(create_error=RuntimeError("Git 创建失败"))

    with pytest.raises(RuntimeError, match="Git 创建失败"):
        service.create_worktree(
            name="api-login",
            task_id="task-api",
            operation_id="call-create-1",
        )

    assert gateway.calls == [("create", "api-login", None)]
    assert bindings.bind_calls == []
    assert journal.events == []


def test_create_worktree_rejects_a_task_already_bound_to_another_name_before_git() -> None:
    service, gateway, journal, _ = _service(
        task=bind_worktree(
            Task.create(task_id="task-api", subject="实现 API。"),
            worktree="web-page",
        )
    )

    with pytest.raises(TaskWorktreeAlreadyBoundError, match="web-page.*api-login"):
        service.create_worktree(
            name="api-login",
            task_id="task-api",
            operation_id="call-create-1",
        )

    assert gateway.calls == []
    assert journal.events == []


def test_remove_worktree_refuses_dirty_or_unpushed_work_without_an_event() -> None:
    service, gateway, journal, bindings = _service(changes=WorktreeChanges(2, 1))

    with pytest.raises(WorktreeUnsafeToRemoveError, match="discard_changes=true"):
        service.remove_worktree(name="api-login", operation_id="call-remove-1")

    assert gateway.calls == [("inspect_changes", "api-login", None)]
    assert journal.events == []
    assert bindings.task.worktree is None


def test_remove_worktree_with_discard_skips_safety_check_and_keeps_task_unchanged() -> None:
    task = bind_worktree(
        Task.create(task_id="task-api", subject="实现 API。"),
        worktree="api-login",
    )
    service, gateway, journal, bindings = _service(
        task=task,
        changes=WorktreeChanges(2, 1),
    )

    result = service.remove_worktree(
        name="api-login",
        operation_id="call-remove-1",
        discard_changes=True,
    )

    assert gateway.calls == [("remove", "api-login", True)]
    assert result.event.event_type.value == "remove"
    assert journal.events == [result.event]
    assert bindings.task == task


def test_remove_worktree_does_not_append_an_event_when_git_removal_fails() -> None:
    service, gateway, journal, _ = _service(remove_error=RuntimeError("Git 删除失败"))

    with pytest.raises(RuntimeError, match="Git 删除失败"):
        service.remove_worktree(name="api-login", operation_id="call-remove-1")

    assert gateway.calls == [
        ("inspect_changes", "api-login", None),
        ("remove", "api-login", False),
    ]
    assert journal.events == []


def test_keep_worktree_records_a_lifecycle_event_without_mutating_the_task() -> None:
    task = bind_worktree(
        Task.create(task_id="task-api", subject="实现 API。"),
        worktree="api-login",
    )
    service, gateway, journal, bindings = _service(task=task)

    result = service.keep_worktree(name="api-login", operation_id="call-keep-1")

    assert gateway.calls == [("keep", "api-login", None)]
    assert result.event.event_type.value == "keep"
    assert result.event.task_id is None
    assert journal.events == [result.event]
    assert bindings.task == task


def test_reusing_an_operation_id_for_another_lifecycle_action_is_rejected() -> None:
    service, _, _, _ = _service()
    service.keep_worktree(name="api-login", operation_id="call-1")

    with pytest.raises(WorktreeOperationConflictError, match="call-1"):
        service.remove_worktree(name="api-login", operation_id="call-1")


def test_service_rejects_incomplete_ports() -> None:
    with pytest.raises(TypeError, match="工作树生命周期网关"):
        WorktreeService(
            object(),
            InMemoryWorktreeEventJournal(),
            FixedClock(),
            InMemoryTaskBindings(Task.create(task_id="task-api", subject="实现 API。")),
            InMemoryTaskBindings(Task.create(task_id="task-api", subject="实现 API。")),
        )

    with pytest.raises(WorktreeError):
        _service()[0].create_worktree(
            name="../api-login",
            operation_id="call-create-1",
        )
