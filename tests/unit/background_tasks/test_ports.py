from pathlib import Path

from local_dev_agent.background_tasks import (
    BackgroundTask,
    BackgroundTaskIdGenerator,
    BackgroundTaskRepository,
    CommandExecutionResult,
    CommandRunner,
)


class InMemoryBackgroundTaskRepository:
    """以结构化实现验证仓储端口不依赖具体基础设施。"""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}

    def add(self, task: BackgroundTask) -> BackgroundTask:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list_for_session(self, session_id: str) -> tuple[BackgroundTask, ...]:
        return tuple(task for task in self._tasks.values() if task.session_id == session_id)

    def replace(self, task: BackgroundTask) -> BackgroundTask:
        self._tasks[task.task_id] = task
        return task


class SequenceBackgroundTaskIdGenerator:
    """用稳定标识验证标识生成器端口。"""

    def new_task_id(self) -> str:
        return "bg-001"


class FixedCommandRunner:
    """用固定结果验证命令运行端口。"""

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        return CommandExecutionResult(exit_code=0, output=f"{working_directory}:{command}")


def test_background_task_ports_accept_structural_implementations(tmp_path: Path) -> None:
    repository: BackgroundTaskRepository = InMemoryBackgroundTaskRepository()
    id_generator: BackgroundTaskIdGenerator = SequenceBackgroundTaskIdGenerator()
    runner: CommandRunner = FixedCommandRunner()
    task = BackgroundTask.create(
        task_id=id_generator.new_task_id(),
        session_id="session-001",
        run_id="run-001",
        tool_call_id="toolu-001",
        command="python -m pytest",
    )

    assert repository.add(task) is task
    assert repository.get("bg-001") is task
    assert repository.list_for_session("session-001") == (task,)
    assert runner.run(command=task.command, working_directory=tmp_path).exit_code == 0
