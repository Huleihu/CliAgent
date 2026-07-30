from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from local_dev_agent.background_tasks import (
    BackgroundTask,
    BackgroundTaskExecutionService,
    BackgroundTaskStatus,
    CommandExecutionResult,
    InMemoryBackgroundTaskRepository,
    SequentialBackgroundTaskIdGenerator,
    ThreadedBackgroundTaskService,
)


class BlockingCommandRunner:
    """用事件控制线程时序，避免测试依赖真实命令或固定等待。"""

    def __init__(self, result: CommandExecutionResult) -> None:
        self._result = result
        self.started = Event()
        self.release = Event()

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        self.started.set()
        if not self.release.wait(timeout=1):
            raise AssertionError("测试未释放后台命令执行器。")
        return self._result


class FailingCommandRunner:
    """模拟命令执行器在启动后抛出的基础设施异常。"""

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        raise RuntimeError("子进程不可用。")


class RecordingBackgroundTaskRepository(InMemoryBackgroundTaskRepository):
    """记录终态替换完成时刻，供线程测试可靠等待。"""

    def __init__(self) -> None:
        super().__init__()
        self.replaced = Event()

    def replace(self, task: BackgroundTask) -> BackgroundTask:
        result = super().replace(task)
        self.replaced.set()
        return result


def _service(
    runner: object,
    *,
    repository: RecordingBackgroundTaskRepository | None = None,
    max_output_summary_chars: int = 200,
) -> tuple[ThreadedBackgroundTaskService, RecordingBackgroundTaskRepository]:
    active_repository = repository or RecordingBackgroundTaskRepository()
    return (
        ThreadedBackgroundTaskService(
            active_repository,
            SequentialBackgroundTaskIdGenerator(),
            runner,  # type: ignore[arg-type]
            max_output_summary_chars=max_output_summary_chars,
        ),
        active_repository,
    )


def _start(service: ThreadedBackgroundTaskService, tmp_path: Path) -> BackgroundTask:
    return service.start(
        session_id="session-001",
        run_id="run-001",
        tool_call_id="toolu-001",
        command="python -m pytest",
        working_directory=tmp_path,
    )


def test_threaded_service_persists_running_snapshot_before_blocking_runner_finishes(
    tmp_path: Path,
) -> None:
    runner = BlockingCommandRunner(CommandExecutionResult(exit_code=0, output="42 passed"))
    service, repository = _service(runner)

    task = _start(service, tmp_path)

    assert runner.started.wait(timeout=1)
    assert task.status is BackgroundTaskStatus.RUNNING
    assert repository.get(task.task_id) is task
    runner.release.set()
    assert repository.replaced.wait(timeout=1)


def test_threaded_service_completes_successful_command_and_bounds_output_summary(
    tmp_path: Path,
) -> None:
    runner = BlockingCommandRunner(CommandExecutionResult(exit_code=0, output="abcdef"))
    service, repository = _service(runner, max_output_summary_chars=4)

    task = _start(service, tmp_path)
    assert runner.started.wait(timeout=1)
    runner.release.set()
    assert repository.replaced.wait(timeout=1)
    completed = repository.get(task.task_id)

    assert completed is not None
    assert completed.status is BackgroundTaskStatus.COMPLETED
    assert completed.exit_code == 0
    assert completed.output_summary == "abcd"


def test_threaded_service_records_nonzero_command_result_as_failure(tmp_path: Path) -> None:
    runner = BlockingCommandRunner(CommandExecutionResult(exit_code=2, output="测试失败"))
    service, repository = _service(runner)

    task = _start(service, tmp_path)
    assert runner.started.wait(timeout=1)
    runner.release.set()
    assert repository.replaced.wait(timeout=1)
    failed = repository.get(task.task_id)

    assert failed is not None
    assert failed.status is BackgroundTaskStatus.FAILED
    assert failed.exit_code == 2
    assert failed.output_summary == "测试失败"
    assert failed.failure_reason is None


def test_threaded_service_converts_command_runner_exception_to_failed_snapshot(
    tmp_path: Path,
) -> None:
    service, repository = _service(FailingCommandRunner())

    task = _start(service, tmp_path)

    assert repository.replaced.wait(timeout=1)
    failed = repository.get(task.task_id)
    assert failed is not None
    assert failed.status is BackgroundTaskStatus.FAILED
    assert failed.exit_code is None
    assert failed.failure_reason == "命令执行器发生 RuntimeError：子进程不可用。"


def test_threaded_service_satisfies_the_structural_execution_service_port(tmp_path: Path) -> None:
    runner = BlockingCommandRunner(CommandExecutionResult(exit_code=0, output="完成"))
    service, repository = _service(runner)
    execution_service: BackgroundTaskExecutionService = service

    task = _start(execution_service, tmp_path)

    assert runner.started.wait(timeout=1)
    assert repository.get(task.task_id) is task
    runner.release.set()
    assert repository.replaced.wait(timeout=1)


@pytest.mark.parametrize(
    ("repository", "id_generator", "command_runner", "max_output_summary_chars", "message"),
    [
        (object(), SequentialBackgroundTaskIdGenerator(), FailingCommandRunner(), 200, "后台任务仓储必须提供"),
        (InMemoryBackgroundTaskRepository(), object(), FailingCommandRunner(), 200, "后台任务标识生成器必须提供"),
        (InMemoryBackgroundTaskRepository(), SequentialBackgroundTaskIdGenerator(), object(), 200, "命令执行器必须提供"),
        (InMemoryBackgroundTaskRepository(), SequentialBackgroundTaskIdGenerator(), FailingCommandRunner(), 0, "max_output_summary_chars”必须是正整数"),
    ],
)
def test_threaded_service_validates_its_dependencies(
    repository: object,
    id_generator: object,
    command_runner: object,
    max_output_summary_chars: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        ThreadedBackgroundTaskService(
            repository,  # type: ignore[arg-type]
            id_generator,  # type: ignore[arg-type]
            command_runner,  # type: ignore[arg-type]
            max_output_summary_chars=max_output_summary_chars,  # type: ignore[arg-type]
        )
