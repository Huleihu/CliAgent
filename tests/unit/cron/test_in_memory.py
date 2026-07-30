from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import (
    CronTask,
    CronTaskAlreadyExistsError,
    CronTaskNotFoundError,
    CronTaskScope,
    InMemoryCronTaskRepository,
)


def _task(
    task_id: str = "cron-001",
    *,
    session_id: str = "session-001",
) -> CronTask:
    return CronTask.create(
        task_id=task_id,
        cron="0 9 * * *",
        prompt="运行检查。",
        owner_session_id=session_id,
        created_at=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc),
    )


def test_in_memory_repository_isolates_sessions_and_replaces_snapshots() -> None:
    repository = InMemoryCronTaskRepository()
    task = _task()
    other_session_task = _task("cron-002", session_id="session-002")

    assert repository.add(task) is task
    repository.add(other_session_task)
    marked = task.mark_enqueued(
        minute=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
    )

    assert repository.list_visible_to_session("session-001") == (task,)
    assert repository.replace(marked) is marked
    assert repository.get(task.task_id) is marked
    assert repository.remove(task.task_id) is marked
    assert repository.get(task.task_id) is None


def test_in_memory_repository_rejects_duplicate_missing_or_durable_tasks() -> None:
    repository = InMemoryCronTaskRepository()
    task = _task()
    repository.add(task)

    with pytest.raises(CronTaskAlreadyExistsError, match="cron-001.*已存在"):
        repository.add(task)
    with pytest.raises(CronTaskNotFoundError, match="cron-missing.*不存在"):
        repository.replace(_task("cron-missing"))
    with pytest.raises(ValueError, match="只能保存 session-only"):
        repository.add(
            CronTask.create(
                task_id="cron-durable",
                cron="0 9 * * *",
                prompt="运行检查。",
                scope=CronTaskScope.DURABLE,
            )
        )


def test_in_memory_repository_keeps_task_ids_unique_under_concurrent_adds() -> None:
    repository = InMemoryCronTaskRepository()
    tasks = tuple(_task(f"cron-{index:03d}") for index in range(16))

    with ThreadPoolExecutor(max_workers=8) as executor:
        saved = tuple(executor.map(repository.add, tasks))

    assert {task.task_id for task in saved} == {task.task_id for task in tasks}
    assert len(repository.list_visible_to_session("session-001")) == 16
