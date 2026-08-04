from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.tasks import Task, TaskStatus


def test_task_create_builds_a_pending_snapshot_and_copies_dependencies() -> None:
    dependencies = ["task-schema"]

    task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        description="新增登录端点。",
        blocked_by=dependencies,
    )
    dependencies.append("task-auth")

    assert task.status is TaskStatus.PENDING
    assert task.owner is None
    assert task.blocked_by == ("task-schema",)
    assert task.worktree is None


def test_task_accepts_an_empty_description() -> None:
    task = Task.create(task_id="task-1", subject="补充测试。")

    assert task.description == ""


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"task_id": " ", "subject": "任务"}, "task_id”必须是非空字符串"),
        ({"task_id": "task-1", "subject": " "}, "subject”必须是非空字符串"),
        ({"task_id": "task-1", "subject": "任务", "description": 1}, "description”必须是字符串"),
        ({"task_id": "task-1", "subject": "任务", "owner": " "}, "owner”必须是非空字符串"),
        ({"task_id": "task-1", "subject": "任务", "worktree": " "}, "worktree”必须是非空字符串"),
    ],
)
def test_task_rejects_invalid_text_fields(
    values: dict[str, object],
    message: str,
) -> None:
    defaults: dict[str, object] = {
        "task_id": "task-1",
        "subject": "任务",
        "description": "",
        "status": TaskStatus.PENDING,
        "owner": None,
        "blocked_by": (),
    }
    defaults.update(values)

    with pytest.raises(ValueError, match=message):
        Task(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("blocked_by", "message"),
    [
        (["task-1"], "blocked_by”必须是非空字符串元组"),
        (None, "blocked_by”必须是非空字符串元组"),
        (("",), "blocked_by”必须是非空字符串元组"),
        (("task-1", "task-1"), "blocked_by”不能包含重复任务标识"),
    ],
)
def test_task_rejects_invalid_dependency_declarations(
    blocked_by: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Task(
            task_id="task-2",
            subject="实现 API。",
            description="",
            status=TaskStatus.PENDING,
            owner=None,
            blocked_by=blocked_by,  # type: ignore[arg-type]
        )


def test_task_create_rejects_a_non_iterable_dependency_input() -> None:
    with pytest.raises(ValueError, match="blocked_by”必须是非空字符串元组"):
        Task.create(
            task_id="task-2",
            subject="实现 API。",
            blocked_by=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("status", "owner", "message"),
    [
        (TaskStatus.PENDING, "agent-a", "待认领任务不能设置 owner"),
        (TaskStatus.IN_PROGRESS, None, "已认领或已完成任务必须设置 owner"),
        (TaskStatus.COMPLETED, None, "已认领或已完成任务必须设置 owner"),
    ],
)
def test_task_rejects_owner_inconsistent_with_its_status(
    status: TaskStatus,
    owner: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Task(
            task_id="task-1",
            subject="任务。",
            description="",
            status=status,
            owner=owner,
        )


def test_task_is_immutable() -> None:
    task = Task.create(task_id="task-1", subject="任务。")

    with pytest.raises(FrozenInstanceError):
        task.subject = "不能修改"  # type: ignore[misc]


def test_task_accepts_an_optional_worktree_binding() -> None:
    task = Task(
        task_id="task-api",
        subject="实现 API。",
        description="",
        status=TaskStatus.PENDING,
        owner=None,
        worktree="api-login",
    )

    assert task.worktree == "api-login"
