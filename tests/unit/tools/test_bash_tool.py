from __future__ import annotations

from pathlib import Path

import pytest

from local_dev_agent.background_tasks import (
    BackgroundTask,
    BackgroundTaskStatus,
    CommandExecutionResult,
)
from local_dev_agent.hooks import HookEvent, HookRegistry, HookRunner
from local_dev_agent.permissions import PermissionHook, SimplePermissionPolicy
from local_dev_agent.tools import ToolCallRequest, ToolExecutionContext, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import BashTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError
from local_dev_agent.tools.workspace import InMemoryRunWorkingDirectoryRegistry


class RecordingCommandRunner:
    """记录前台调用，避免工具测试执行真实 shell 命令。"""

    def __init__(self, result: CommandExecutionResult) -> None:
        self._result = result
        self.calls: list[tuple[str, Path]] = []

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        self.calls.append((command, working_directory))
        return self._result


class RecordingBackgroundTaskService:
    """记录后台派发关联，验证工具不直接管理线程。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        command: str,
        working_directory: Path,
    ) -> BackgroundTask:
        self.calls.append(
            {
                "session_id": session_id,
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "command": command,
                "working_directory": working_directory,
            }
        )
        return BackgroundTask.create(
            task_id="bg_0001",
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            command=command,
        )


def _tool(tmp_path: Path) -> tuple[BashTool, RecordingCommandRunner, RecordingBackgroundTaskService]:
    command_runner = RecordingCommandRunner(
        CommandExecutionResult(exit_code=0, output="命令完成")
    )
    background_service = RecordingBackgroundTaskService()
    return (
        BashTool(tmp_path, command_runner, background_service),
        command_runner,
        background_service,
    )


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="session-001",
        run_id="run-001",
        step_id="step-001",
        call_id="toolu-001",
    )


def test_bash_tool_runs_fast_command_in_foreground(tmp_path: Path) -> None:
    tool, command_runner, background_service = _tool(tmp_path)

    result = tool.run({"command": "git status"})

    assert result == {"exit_code": 0, "output": "命令完成"}
    assert command_runner.calls == [("git status", tmp_path.resolve())]
    assert background_service.calls == []


def test_bash_tool_dispatches_explicit_background_command_with_execution_context(
    tmp_path: Path,
) -> None:
    tool, command_runner, background_service = _tool(tmp_path)

    result = tool.run(
        {"command": "git status", "run_in_background": True},
        context=_context(),
    )

    assert result == {
        "bg_id": "bg_0001",
        "status": BackgroundTaskStatus.RUNNING.value,
        "command": "git status",
    }
    assert command_runner.calls == []
    assert background_service.calls == [
        {
            "session_id": "session-001",
            "run_id": "run-001",
            "tool_call_id": "toolu-001",
            "command": "git status",
            "working_directory": tmp_path.resolve(),
        }
    ]


def test_bash_tool_uses_the_same_run_workspace_for_foreground_and_background_commands(
    tmp_path: Path,
) -> None:
    main_workspace = tmp_path / "main"
    worktree = main_workspace / ".worktrees" / "api-login"
    worktree.mkdir(parents=True)
    registry = InMemoryRunWorkingDirectoryRegistry(main_workspace=main_workspace)
    registry.bind(run_id="run-001", directory=worktree)
    command_runner = RecordingCommandRunner(CommandExecutionResult(exit_code=0, output="完成"))
    background_service = RecordingBackgroundTaskService()
    tool = BashTool(
        main_workspace,
        command_runner,
        background_service,
        working_directory_resolver=registry,
    )

    tool.run({"command": "git status"}, context=_context())
    tool.run({"command": "python -m pytest", "run_in_background": True}, context=_context())

    assert command_runner.calls == [("git status", worktree.resolve())]
    assert background_service.calls[0]["working_directory"] == worktree.resolve()


def test_bash_tool_uses_slow_command_heuristic_only_when_model_omits_the_flag(
    tmp_path: Path,
) -> None:
    tool, command_runner, background_service = _tool(tmp_path)

    background_result = tool.run({"command": "python -m pytest"}, context=_context())
    foreground_result = tool.run(
        {"command": "python -m pytest", "run_in_background": False}
    )

    assert background_result["bg_id"] == "bg_0001"
    assert foreground_result == {"exit_code": 0, "output": "命令完成"}
    assert len(background_service.calls) == 1
    assert command_runner.calls == [("python -m pytest", tmp_path.resolve())]


def test_bash_tool_rejects_background_dispatch_without_a_call_association(tmp_path: Path) -> None:
    tool, _, background_service = _tool(tmp_path)

    with pytest.raises(ToolExecutionError, match="带工具调用标识的执行上下文"):
        tool.run({"command": "git status", "run_in_background": True})

    assert background_service.calls == []


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"command": " "}, "command”必须是非空字符串"),
        ({"command": "git status", "run_in_background": "yes"}, "run_in_background”必须是布尔值"),
    ],
)
def test_bash_tool_rejects_invalid_direct_arguments(
    tmp_path: Path,
    arguments: dict[str, object],
    message: str,
) -> None:
    tool, _, _ = _tool(tmp_path)

    with pytest.raises(ToolValidationError, match=message):
        tool.run(arguments)


def test_bash_tool_reuses_standard_permission_boundary_before_background_dispatch(
    tmp_path: Path,
) -> None:
    tool, _, background_service = _tool(tmp_path)
    registry = ToolRegistry()
    registry.register(tool)
    hooks = HookRegistry()
    hooks.register(
        HookEvent.PRE_TOOL_USE,
        PermissionHook(
            SimplePermissionPolicy(tmp_path, approval_prompt=lambda _context, _reason: False)
        ),
    )

    result = ToolExecutor(registry, hook_runner=HookRunner(hooks)).execute(
        ToolCallRequest(
            name="bash",
            arguments={"command": "rm temporary.txt", "run_in_background": True},
            call_id="toolu-001",
        ),
        context=_context(),
    )

    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ToolHookBlockedError"
    assert background_service.calls == []


@pytest.mark.parametrize(
    ("workspace", "runner", "service", "message"),
    [
        ("不是路径", RecordingCommandRunner(CommandExecutionResult(0, "")), RecordingBackgroundTaskService(), "workspace 必须是 Path 对象"),
        (Path("."), object(), RecordingBackgroundTaskService(), "命令执行器必须提供"),
        (Path("."), RecordingCommandRunner(CommandExecutionResult(0, "")), object(), "后台任务执行服务必须提供"),
    ],
)
def test_bash_tool_validates_constructor_dependencies(
    workspace: object,
    runner: object,
    service: object,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        BashTool(workspace, runner, service)  # type: ignore[arg-type]
