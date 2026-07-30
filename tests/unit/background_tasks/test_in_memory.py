from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.background_tasks import (
    BackgroundTask,
    BackgroundTaskAlreadyExistsError,
    BackgroundTaskNotFoundError,
    InMemoryBackgroundTaskRepository,
    SequentialBackgroundTaskIdGenerator,
)


def _task(
    task_id: str = "bg_0001",
    *,
    session_id: str = "session-001",
    minute: int = 0,
) -> BackgroundTask:
    return BackgroundTask.create(
        task_id=task_id,
        session_id=session_id,
        run_id="run-001",
        tool_call_id=f"toolu-{task_id}",
        command="python -m pytest",
        created_at=datetime(
            2026,
            7,
            30,
            8,
            minute,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )


def test_in_memory_repository_adds_gets_replaces_and_sorts_session_snapshots() -> None:
    repository = InMemoryBackgroundTaskRepository()
    later_task = _task("bg_0002", minute=1)
    earlier_task = _task("bg_0001")

    repository.add(later_task)
    repository.add(earlier_task)
    completed = earlier_task.complete(output_summary="42 passed")

    assert repository.get("bg_0001") is earlier_task
    assert repository.replace(completed) is completed
    assert repository.get("bg_0001") is completed
    assert repository.list_for_session("session-001") == (completed, later_task)


def test_in_memory_repository_isolates_sessions_and_rejects_duplicate_or_missing_tasks() -> None:
    repository = InMemoryBackgroundTaskRepository()
    task = _task()
    repository.add(task)
    repository.add(_task("bg_0002", session_id="session-002"))

    assert repository.list_for_session("session-001") == (task,)
    with pytest.raises(BackgroundTaskAlreadyExistsError, match="bg_0001.*已存在"):
        repository.add(task)
    with pytest.raises(BackgroundTaskNotFoundError, match="bg-missing.*不存在"):
        repository.replace(_task("bg-missing"))


def test_in_memory_repository_refuses_replacement_that_changes_task_identity() -> None:
    repository = InMemoryBackgroundTaskRepository()
    task = _task()
    repository.add(task)
    changed_identity = BackgroundTask.create(
        task_id=task.task_id,
        session_id=task.session_id,
        run_id=task.run_id,
        tool_call_id=task.tool_call_id,
        command="python -m ruff check src",
        created_at=task.created_at,
    )

    with pytest.raises(ValueError, match="不能改变任务归属、调用关联或命令"):
        repository.replace(changed_identity)


def test_sequential_identifier_generator_produces_stable_zero_padded_identifiers() -> None:
    generator = SequentialBackgroundTaskIdGenerator(start=8, width=4)

    assert generator.new_task_id() == "bg_0008"
    assert generator.new_task_id() == "bg_0009"


def test_sequential_identifier_generator_keeps_identifiers_unique_under_concurrent_calls() -> None:
    generator = SequentialBackgroundTaskIdGenerator()

    with ThreadPoolExecutor(max_workers=8) as executor:
        task_ids = tuple(executor.map(_new_task_id, (generator,) * 32))

    assert len(set(task_ids)) == 32
    assert sorted(task_ids) == [f"bg_{value:04d}" for value in range(1, 33)]


def _new_task_id(generator: SequentialBackgroundTaskIdGenerator) -> str:
    """供并发测试调用同一个生成器实例。"""

    return generator.new_task_id()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"prefix": " "}, "prefix”必须是非空字符串"),
        ({"start": 0}, "start”必须是大于或等于 1 的整数"),
        ({"width": 0}, "width”必须是大于或等于 1 的整数"),
    ],
)
def test_sequential_identifier_generator_validates_configuration(
    arguments: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SequentialBackgroundTaskIdGenerator(**arguments)  # type: ignore[arg-type]
