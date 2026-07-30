from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import (
    CronExpressionValidationError,
    CronTask,
    CronTaskAlreadyExistsError,
    CronTaskNotFoundError,
    CronTaskScope,
    CronTaskService,
)


class SequenceIdGenerator:
    """按给定顺序提供标识，验证应用服务的跨仓储冲突检查。"""

    def __init__(self, task_ids: tuple[str, ...] = ("cron-001", "cron-002")) -> None:
        self._task_ids = list(task_ids)
        self.calls = 0

    def new_task_id(self) -> str:
        self.calls += 1
        return self._task_ids.pop(0)


class FixedClock:
    """为服务测试提供稳定的带时区创建时间。"""

    def now(self) -> datetime:
        return datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


class AllScopeCronTaskRepository:
    """用结构化内存仓储验证服务按 scope 路由，不混入适配器限制。"""

    def __init__(self) -> None:
        self._tasks: dict[str, CronTask] = {}

    def add(self, task: CronTask) -> CronTask:
        if task.task_id in self._tasks:
            raise CronTaskAlreadyExistsError(task_id=task.task_id)
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> CronTask | None:
        return self._tasks.get(task_id)

    def list_visible_to_session(self, session_id: str) -> tuple[CronTask, ...]:
        return tuple(task for task in self._tasks.values() if task.is_visible_to(session_id))

    def replace(self, task: CronTask) -> CronTask:
        if task.task_id not in self._tasks:
            raise CronTaskNotFoundError(task_id=task.task_id)
        self._tasks[task.task_id] = task
        return task

    def remove(self, task_id: str) -> CronTask | None:
        return self._tasks.pop(task_id, None)


def _service(
    *,
    session_repository: AllScopeCronTaskRepository | None = None,
    durable_repository: AllScopeCronTaskRepository | None = None,
    id_generator: SequenceIdGenerator | None = None,
) -> tuple[
    CronTaskService,
    AllScopeCronTaskRepository,
    AllScopeCronTaskRepository,
    SequenceIdGenerator,
]:
    session = session_repository or AllScopeCronTaskRepository()
    durable = durable_repository or AllScopeCronTaskRepository()
    generator = id_generator or SequenceIdGenerator()
    return (
        CronTaskService(
            session_repository=session,
            durable_repository=durable,
            id_generator=generator,
            clock=FixedClock(),
        ),
        session,
        durable,
        generator,
    )


def test_service_registers_canonical_session_only_definition_after_parsing() -> None:
    service, session_repository, _, generator = _service()

    task = service.schedule(
        session_id="session-001",
        cron="  0   9  * * *  ",
        prompt="运行检查。",
    )

    assert task.task_id == "cron-001"
    assert task.cron == "0 9 * * *"
    assert task.scope is CronTaskScope.SESSION_ONLY
    assert task.owner_session_id == "session-001"
    assert session_repository.get(task.task_id) is task
    assert generator.calls == 1


def test_service_registers_durable_definition_without_session_owner() -> None:
    service, _, durable_repository, _ = _service()

    task = service.schedule(
        session_id="session-001",
        cron="0 9 * * 1-5",
        prompt="运行每日检查。",
        durable=True,
    )

    assert task.scope is CronTaskScope.DURABLE
    assert task.owner_session_id is None
    assert durable_repository.get(task.task_id) is task


def test_service_rejects_invalid_expression_before_generating_an_id_or_writing() -> None:
    service, session_repository, _, generator = _service()

    with pytest.raises(CronExpressionValidationError, match="字段“分钟”"):
        service.schedule(
            session_id="session-001",
            cron="60 * * * *",
            prompt="不应保存。",
        )

    assert generator.calls == 0
    assert session_repository.list_visible_to_session("session-001") == ()


def test_service_lists_own_session_tasks_with_workspace_durable_tasks_and_cancels_them() -> None:
    service, _, _, _ = _service()
    session_task = service.schedule(
        session_id="session-001",
        cron="0 9 * * *",
        prompt="Session 检查。",
    )
    durable_task = service.schedule(
        session_id="session-001",
        cron="0 10 * * *",
        prompt="工作区检查。",
        durable=True,
    )

    assert [task.task_id for task in service.list_for_session(session_id="session-001")] == [
        session_task.task_id,
        durable_task.task_id,
    ]
    assert service.list_for_session(session_id="session-002") == (durable_task,)
    assert service.cancel(session_id="session-001", task_id=session_task.task_id) is session_task
    assert service.cancel(session_id="session-002", task_id=durable_task.task_id) is durable_task


def test_service_cannot_cancel_another_sessions_session_only_task() -> None:
    service, _, _, _ = _service()
    task = service.schedule(
        session_id="session-001",
        cron="0 9 * * *",
        prompt="私有检查。",
    )

    with pytest.raises(CronTaskNotFoundError, match=task.task_id):
        service.cancel(session_id="session-002", task_id=task.task_id)


def test_service_detects_a_generator_collision_across_scope_repositories() -> None:
    service, session_repository, _, _ = _service(
        id_generator=SequenceIdGenerator(("cron-001",))
    )
    session_repository.add(
        CronTask.create(
            task_id="cron-001",
            cron="0 9 * * *",
            prompt="已存在。",
            owner_session_id="session-001",
            created_at=FixedClock().now(),
        )
    )

    with pytest.raises(CronTaskAlreadyExistsError, match="cron-001.*已存在"):
        service.schedule(
            session_id="session-001",
            cron="0 10 * * *",
            prompt="不应保存。",
        )
