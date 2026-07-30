"""通过既有受控工具链执行前台或后台 shell 命令。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from local_dev_agent.background_tasks import (
    BackgroundExecutionPolicy,
    BackgroundTaskExecutionService,
    CommandRunner,
)

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


class BashTool(Tool):
    """把命令执行选择收束在工具内，不向 Runtime 泄漏后台领域逻辑。"""

    def __init__(
        self,
        workspace: Path,
        command_runner: CommandRunner,
        background_task_service: BackgroundTaskExecutionService,
        *,
        background_execution_policy: BackgroundExecutionPolicy | None = None,
    ) -> None:
        if not isinstance(workspace, Path):
            raise TypeError("workspace 必须是 Path 对象。")
        if not callable(getattr(command_runner, "run", None)):
            raise TypeError("命令执行器必须提供 run 方法。")
        if not callable(getattr(background_task_service, "start", None)):
            raise TypeError("后台任务执行服务必须提供 start 方法。")
        if background_execution_policy is not None and not isinstance(
            background_execution_policy,
            BackgroundExecutionPolicy,
        ):
            raise TypeError("background_execution_policy 必须是 BackgroundExecutionPolicy 对象。")
        self._workspace = workspace.resolve()
        self._command_runner = command_runner
        self._background_task_service = background_task_service
        self._background_execution_policy = (
            background_execution_policy or BackgroundExecutionPolicy()
        )
        self._definition = ToolDefinition(
            name="bash",
            description="在工作区运行一条 shell 命令；可显式请求后台执行慢命令。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "需要在工作区执行的 shell 命令。",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "是否显式要求在后台执行；未提供时由保守策略判断。",
                    },
                },
                "required": ["command"],
            },
            tags=("command",),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回可供模型选择的命令执行协议。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """前台返回命令结果，后台仅返回已派发任务的稳定关联信息。"""

        command = _read_command(arguments)
        requested_background = _read_optional_boolean(arguments, "run_in_background")
        if self._background_execution_policy.should_run_in_background(
            command=command,
            requested=requested_background,
        ):
            return self._start_background_task(command=command, context=context)
        try:
            result = self._command_runner.run(
                command=command,
                working_directory=self._workspace,
            )
        except Exception as error:
            raise ToolExecutionError(f"命令执行失败：{error}") from error
        return {
            "exit_code": result.exit_code,
            "output": result.output,
        }

    def _start_background_task(
        self,
        *,
        command: str,
        context: ToolExecutionContext | None,
    ) -> Mapping[str, object]:
        """要求完整调用关联后派发任务，避免后台结果跨 Session 泄漏。"""

        if context is None or context.call_id is None:
            raise ToolExecutionError("后台命令必须在带工具调用标识的执行上下文中启动。")
        try:
            task = self._background_task_service.start(
                session_id=context.session_id,
                run_id=context.run_id,
                tool_call_id=context.call_id,
                command=command,
                working_directory=self._workspace,
            )
        except Exception as error:
            raise ToolExecutionError(f"后台命令派发失败：{error}") from error
        return {
            "bg_id": task.task_id,
            "status": task.status.value,
            "command": task.command,
        }


def _read_command(arguments: Mapping[str, object]) -> str:
    """读取并校验 shell 命令文本。"""

    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolValidationError("字段“command”必须是非空字符串。")
    return command


def _read_optional_boolean(arguments: Mapping[str, object], field_name: str) -> bool | None:
    """区分未声明参数与模型显式提供的布尔选择。"""

    if field_name not in arguments:
        return None
    value = arguments[field_name]
    if not isinstance(value, bool):
        raise ToolValidationError(f"字段“{field_name}”必须是布尔值。")
    return value
