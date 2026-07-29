import pytest

from local_dev_agent.tasks import (
    Task,
    TaskBlockedError,
    TaskStateTransitionError,
    TaskStatus,
    can_claim_task,
    claim_task,
    complete_task,
    unresolved_dependency_ids,
)


def _completed_task(task_id: str) -> Task:
    return Task(
        task_id=task_id,
        subject=f"{task_id} 已完成。",
        description="",
        status=TaskStatus.COMPLETED,
        owner="agent-a",
    )


def test_unresolved_dependency_ids_includes_missing_and_incomplete_dependencies() -> None:
    task = Task.create(
        task_id="task-tests",
        subject="编写测试。",
        blocked_by=("task-schema", "task-api", "task-missing"),
    )
    api_task = Task.create(task_id="task-api", subject="实现 API。")

    assert unresolved_dependency_ids(
        task,
        {"task-schema": _completed_task("task-schema"), "task-api": api_task},
    ) == ("task-api", "task-missing")


def test_can_claim_task_requires_pending_status_and_completed_dependencies() -> None:
    task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        blocked_by=("task-schema",),
    )
    dependencies = {"task-schema": _completed_task("task-schema")}

    claimed_task = claim_task(task, owner="agent-api", dependencies=dependencies)

    assert can_claim_task(task, dependencies)
    assert not can_claim_task(claimed_task, dependencies)


def test_claim_task_returns_a_new_owned_in_progress_snapshot() -> None:
    task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        description="新增登录端点。",
        blocked_by=("task-schema",),
    )

    claimed = claim_task(
        task,
        owner="agent-api",
        dependencies={"task-schema": _completed_task("task-schema")},
    )

    assert task.status is TaskStatus.PENDING
    assert task.owner is None
    assert claimed.status is TaskStatus.IN_PROGRESS
    assert claimed.owner == "agent-api"
    assert claimed.blocked_by == ("task-schema",)


def test_claim_task_rejects_blocked_tasks() -> None:
    task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        blocked_by=("task-schema", "task-auth"),
    )

    with pytest.raises(TaskBlockedError, match="task-schema、task-auth"):
        claim_task(task, owner="agent-api", dependencies={})


def test_claim_task_rejects_a_task_that_is_not_pending() -> None:
    task = _completed_task("task-api")

    with pytest.raises(TaskStateTransitionError, match="不能执行“认领”"):
        claim_task(task, owner="agent-api", dependencies={})


def test_complete_task_returns_a_new_completed_snapshot_and_keeps_owner() -> None:
    in_progress = Task(
        task_id="task-api",
        subject="实现 API。",
        description="",
        status=TaskStatus.IN_PROGRESS,
        owner="agent-api",
        blocked_by=("task-schema",),
    )

    completed = complete_task(in_progress)

    assert in_progress.status is TaskStatus.IN_PROGRESS
    assert completed.status is TaskStatus.COMPLETED
    assert completed.owner == "agent-api"
    assert completed.blocked_by == ("task-schema",)


@pytest.mark.parametrize("status", (TaskStatus.PENDING, TaskStatus.COMPLETED))
def test_complete_task_requires_an_in_progress_task(status: TaskStatus) -> None:
    task = (
        Task.create(task_id="task-api", subject="实现 API。")
        if status is TaskStatus.PENDING
        else _completed_task("task-api")
    )

    with pytest.raises(TaskStateTransitionError, match="不能执行“完成”"):
        complete_task(task)


def test_dependency_rules_reject_invalid_input_types() -> None:
    task = Task.create(task_id="task-api", subject="实现 API。")

    with pytest.raises(TypeError, match="task 必须是 Task 对象"):
        unresolved_dependency_ids("task", {})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="dependencies 必须是"):
        unresolved_dependency_ids(task, {"task-1": "不是任务"})  # type: ignore[arg-type]
