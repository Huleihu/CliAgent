import pytest

from local_dev_agent.tasks import (
    Task,
    TaskBlockedError,
    TaskCompletion,
    TaskIdGenerator,
    TaskNotFoundError,
    TaskService,
    TaskStatus,
)


class InMemoryTaskRepository:
    """模拟任务仓储，验证服务只依赖稳定端口。"""

    def __init__(self, tasks: tuple[Task, ...] = ()) -> None:
        self._tasks = {task.task_id: task for task in tasks}

    def add(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> tuple[Task, ...]:
        return tuple(self._tasks[task_id] for task_id in sorted(self._tasks))

    def replace(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        return task


class SequenceTaskIdGenerator:
    """按预设顺序生成标识，避免服务测试依赖随机性。"""

    def __init__(self, task_ids: tuple[str, ...] = ("task-created",)) -> None:
        self._task_ids = iter(task_ids)

    def new_task_id(self) -> str:
        return next(self._task_ids)


def _service(*tasks: Task) -> TaskService:
    return TaskService(InMemoryTaskRepository(tasks), SequenceTaskIdGenerator())


def _completed_task(task_id: str) -> Task:
    return Task(
        task_id=task_id,
        subject=f"{task_id} 已完成。",
        description="",
        status=TaskStatus.COMPLETED,
        owner="agent-a",
    )


def test_create_task_uses_the_generator_and_persists_a_pending_snapshot() -> None:
    service = _service()

    task = service.create_task(
        subject="实现 API。",
        description="新增登录端点。",
        blocked_by=["task-schema"],
    )

    assert task.task_id == "task-created"
    assert task.status is TaskStatus.PENDING
    assert task.blocked_by == ("task-schema",)
    assert service.get_task("task-created") is task


def test_list_and_get_tasks_delegate_to_the_repository_snapshot() -> None:
    task_a = Task.create(task_id="task-a", subject="任务 A。")
    task_b = Task.create(task_id="task-b", subject="任务 B。")
    service = _service(task_b, task_a)

    assert tuple(task.task_id for task in service.list_tasks()) == ("task-a", "task-b")
    assert service.get_task("task-b") is task_b


def test_get_task_rejects_a_missing_task() -> None:
    with pytest.raises(TaskNotFoundError, match="task-missing.*不存在"):
        _service().get_task("task-missing")


def test_claim_task_resolves_completed_dependencies_and_persists_the_result() -> None:
    schema_task = _completed_task("task-schema")
    api_task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        blocked_by=("task-schema",),
    )
    service = _service(schema_task, api_task)

    claimed = service.claim_task(task_id="task-api", owner="agent-api")

    assert claimed.status is TaskStatus.IN_PROGRESS
    assert claimed.owner == "agent-api"
    assert service.get_task("task-api") is claimed


def test_claim_task_treats_a_missing_dependency_as_blocked() -> None:
    api_task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        blocked_by=("task-schema",),
    )

    with pytest.raises(TaskBlockedError, match="task-schema"):
        _service(api_task).claim_task(task_id="task-api", owner="agent-api")


def test_complete_task_reports_only_downstream_tasks_newly_unblocked_by_completion() -> None:
    schema_task = Task(
        task_id="task-schema",
        subject="建立表结构。",
        description="",
        status=TaskStatus.IN_PROGRESS,
        owner="agent-schema",
    )
    api_task = Task.create(
        task_id="task-api",
        subject="实现 API。",
        blocked_by=("task-schema",),
    )
    tests_task = Task.create(
        task_id="task-tests",
        subject="编写测试。",
        blocked_by=("task-api",),
    )
    service = _service(schema_task, api_task, tests_task)

    completion = service.complete_task(task_id="task-schema")

    assert isinstance(completion, TaskCompletion)
    assert completion.task.status is TaskStatus.COMPLETED
    assert tuple(task.task_id for task in completion.unblocked_tasks) == ("task-api",)
    assert service.get_task("task-schema") is completion.task


def test_complete_task_does_not_report_an_already_unblocked_task_again() -> None:
    schema_task = Task(
        task_id="task-schema",
        subject="建立表结构。",
        description="",
        status=TaskStatus.IN_PROGRESS,
        owner="agent-schema",
    )
    documentation_task = Task.create(
        task_id="task-docs",
        subject="编写文档。",
        blocked_by=("task-ready",),
    )
    ready_task = _completed_task("task-ready")
    service = _service(schema_task, documentation_task, ready_task)

    completion = service.complete_task(task_id="task-schema")

    assert completion.unblocked_tasks == ()


def test_service_rejects_invalid_repository_and_id_generator_ports() -> None:
    with pytest.raises(TypeError, match="任务仓储必须提供"):
        TaskService(object(), SequenceTaskIdGenerator())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="任务标识生成器必须提供"):
        TaskService(InMemoryTaskRepository(), object())  # type: ignore[arg-type]


def test_task_id_generator_port_accepts_a_structural_implementation() -> None:
    generator: TaskIdGenerator = SequenceTaskIdGenerator(("task-1",))

    assert generator.new_task_id() == "task-1"
