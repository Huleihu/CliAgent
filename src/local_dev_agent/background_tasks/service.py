"""后台任务的线程调度应用服务。"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Thread

from .ports import BackgroundTaskIdGenerator, BackgroundTaskRepository, CommandRunner
from .schema import BackgroundTask, CommandExecutionResult

logger = logging.getLogger(__name__)


class ThreadedBackgroundTaskService:
    """先保存运行中快照，再以 daemon 线程执行命令并写回终态。"""

    def __init__(
        self,
        repository: BackgroundTaskRepository,
        id_generator: BackgroundTaskIdGenerator,
        command_runner: CommandRunner,
        *,
        max_output_summary_chars: int = 200,
    ) -> None:
        if not all(
            callable(getattr(repository, method_name, None))
            for method_name in ("add", "get", "list_for_session", "replace")
        ):
            raise TypeError("后台任务仓储必须提供 add、get、list_for_session 和 replace 方法。")
        if not callable(getattr(id_generator, "new_task_id", None)):
            raise TypeError("后台任务标识生成器必须提供 new_task_id 方法。")
        if not callable(getattr(command_runner, "run", None)):
            raise TypeError("命令执行器必须提供 run 方法。")
        if (
            isinstance(max_output_summary_chars, bool)
            or not isinstance(max_output_summary_chars, int)
            or max_output_summary_chars < 1
        ):
            raise ValueError("字段“max_output_summary_chars”必须是正整数。")
        self._repository = repository
        self._id_generator = id_generator
        self._command_runner = command_runner
        self._max_output_summary_chars = max_output_summary_chars

    def start(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        command: str,
        working_directory: Path,
    ) -> BackgroundTask:
        """启动 daemon 线程并立即返回已保存的运行中任务快照。"""

        if not isinstance(working_directory, Path):
            raise TypeError("working_directory 必须是 Path 对象。")
        task = BackgroundTask.create(
            task_id=self._id_generator.new_task_id(),
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            command=command,
        )
        saved_task = self._repository.add(task)
        if not isinstance(saved_task, BackgroundTask):
            raise TypeError("后台任务仓储必须返回 BackgroundTask 对象。")
        thread = Thread(
            target=self._run_task,
            kwargs={"task": saved_task, "working_directory": working_directory},
            daemon=True,
            name=f"background-task-{saved_task.task_id}",
        )
        thread.start()
        return saved_task

    def _run_task(self, *, task: BackgroundTask, working_directory: Path) -> None:
        """在线程中执行命令，并把成功、非零退出或异常收束为终态快照。"""

        try:
            result = self._command_runner.run(
                command=task.command,
                working_directory=working_directory,
            )
            if not isinstance(result, CommandExecutionResult):
                raise TypeError("命令执行器必须返回 CommandExecutionResult 对象。")
            completed_task = self._complete_from_result(task, result)
        except Exception as error:
            completed_task = task.fail(
                output_summary="",
                failure_reason=(
                    f"命令执行器发生 {type(error).__name__}：{error or '未提供详细信息'}"
                ),
            )
            logger.warning(
                "后台命令执行失败。",
                exc_info=True,
                extra={
                    "background_task_id": task.task_id,
                    "session_id": task.session_id,
                    "run_id": task.run_id,
                },
            )
        self._repository.replace(completed_task)

    def _complete_from_result(
        self,
        task: BackgroundTask,
        result: CommandExecutionResult,
    ) -> BackgroundTask:
        """按退出码把命令结果转换为完成或失败快照。"""

        output_summary = self._summarize_output(result.output)
        if result.exit_code == 0:
            return task.complete(output_summary=output_summary)
        return task.fail(exit_code=result.exit_code, output_summary=output_summary)

    def _summarize_output(self, output: str) -> str:
        """限制内存快照大小，为后续通知和持久化保留固定上界。"""

        return output[: self._max_output_summary_chars]
