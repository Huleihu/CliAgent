from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.background_tasks import (
    BackgroundTask,
    BackgroundTaskStatus,
    CommandExecutionResult,
    InvalidBackgroundTaskTransitionError,
)


def _created_at() -> datetime:
    return datetime(2026, 7, 30, 9, 0, tzinfo=timezone(timedelta(hours=8)))


def _task() -> BackgroundTask:
    return BackgroundTask.create(
        task_id="bg-001",
        session_id="session-001",
        run_id="run-001",
        tool_call_id="toolu-001",
        command="python -m pytest",
        created_at=_created_at(),
    )


def test_background_task_starts_running_with_normalized_utc_timestamp() -> None:
    task = _task()

    assert task.status is BackgroundTaskStatus.RUNNING
    assert task.created_at == datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    assert task.finished_at is None
    assert task.exit_code is None
    assert task.output_summary is None
    assert task.is_terminal is False


def test_background_task_is_immutable() -> None:
    task = _task()

    with pytest.raises(FrozenInstanceError):
        task.command = "python -m ruff check src"  # type: ignore[misc]


def test_background_task_completes_with_a_new_terminal_snapshot() -> None:
    task = _task()

    completed = task.complete(
        output_summary="42 passed",
        finished_at=datetime(2026, 7, 30, 1, 5, tzinfo=timezone.utc),
    )

    assert task.status is BackgroundTaskStatus.RUNNING
    assert completed.status is BackgroundTaskStatus.COMPLETED
    assert completed.exit_code == 0
    assert completed.output_summary == "42 passed"
    assert completed.failure_reason is None
    assert completed.is_terminal is True


def test_background_task_records_nonzero_exit_code_as_failure() -> None:
    failed = _task().fail(
        exit_code=1,
        output_summary="1 failed",
        finished_at=datetime(2026, 7, 30, 1, 5, tzinfo=timezone.utc),
    )

    assert failed.status is BackgroundTaskStatus.FAILED
    assert failed.exit_code == 1
    assert failed.output_summary == "1 failed"
    assert failed.failure_reason is None


def test_background_task_records_runner_exception_as_failure() -> None:
    failed = _task().fail(
        output_summary="",
        failure_reason="命令执行器不可用。",
        finished_at=datetime(2026, 7, 30, 1, 5, tzinfo=timezone.utc),
    )

    assert failed.status is BackgroundTaskStatus.FAILED
    assert failed.exit_code is None
    assert failed.failure_reason == "命令执行器不可用。"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: BackgroundTask.create(
                task_id=" ",
                session_id="session-001",
                run_id="run-001",
                tool_call_id="toolu-001",
                command="python -m pytest",
            ),
            "task_id”必须是非空字符串",
        ),
        (
            lambda: BackgroundTask.create(
                task_id="bg-001",
                session_id="session-001",
                run_id="run-001",
                tool_call_id="toolu-001",
                command=" ",
            ),
            "command”必须是非空字符串",
        ),
        (
            lambda: BackgroundTask(
                task_id="bg-001",
                session_id="session-001",
                run_id="run-001",
                tool_call_id="toolu-001",
                command="python -m pytest",
                status=BackgroundTaskStatus.RUNNING,
                created_at=datetime(2026, 7, 30, 1, 0),
            ),
            "created_at”必须是带时区的 datetime",
        ),
    ],
)
def test_background_task_rejects_invalid_identity_and_time(
    factory: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize(
    ("task", "message"),
    [
        (
            lambda: BackgroundTask(
                task_id="bg-001",
                session_id="session-001",
                run_id="run-001",
                tool_call_id="toolu-001",
                command="python -m pytest",
                status=BackgroundTaskStatus.RUNNING,
                created_at=datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc),
                output_summary="不应存在",
            ),
            "运行中的后台任务不能包含终态结果",
        ),
        (
            lambda: BackgroundTask(
                task_id="bg-001",
                session_id="session-001",
                run_id="run-001",
                tool_call_id="toolu-001",
                command="python -m pytest",
                status=BackgroundTaskStatus.COMPLETED,
                created_at=datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 30, 1, 1, tzinfo=timezone.utc),
                exit_code=1,
                output_summary="不一致",
            ),
            "已完成的后台任务必须使用退出码 0",
        ),
        (
            lambda: BackgroundTask(
                task_id="bg-001",
                session_id="session-001",
                run_id="run-001",
                tool_call_id="toolu-001",
                command="python -m pytest",
                status=BackgroundTaskStatus.FAILED,
                created_at=datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 30, 1, 1, tzinfo=timezone.utc),
                output_summary="不一致",
            ),
            "失败的后台任务必须包含非零退出码或失败原因",
        ),
    ],
)
def test_background_task_rejects_inconsistent_lifecycle_fields(
    task: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        task()  # type: ignore[operator]


def test_background_task_rejects_repeated_terminal_transition() -> None:
    completed = _task().complete(output_summary="42 passed")

    with pytest.raises(InvalidBackgroundTaskTransitionError, match="不能转换为“failed”"):
        completed.fail(exit_code=1, output_summary="不应执行")


@pytest.mark.parametrize(
    ("exit_code", "output", "message"),
    [
        (True, "输出", "exit_code”必须是整数或 None"),
        (0, object(), "output”必须是字符串"),
    ],
)
def test_command_execution_result_validates_its_public_contract(
    exit_code: object,
    output: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        CommandExecutionResult(exit_code=exit_code, output=output)  # type: ignore[arg-type]
