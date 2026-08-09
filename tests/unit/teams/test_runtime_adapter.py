from types import SimpleNamespace
from pathlib import Path

import pytest

from local_dev_agent.teams import RuntimeTeamAgentExecutor, TeamMember
from local_dev_agent.tools import ToolExecutionContext
from local_dev_agent.tools.workspace import InMemoryRunWorkingDirectoryRegistry


class RecordingRuntimeService:
    """记录 Team 适配器提交给标准 Runtime 的输入事件。"""

    def __init__(self) -> None:
        self.events: list[object] = []

    def handle(self, event: object) -> object:
        self.events.append(event)
        return SimpleNamespace(run=SimpleNamespace(run_id="run-001"))


class RecordingLoop:
    """返回最小真实 Run/响应形状，验证适配器不自行编造 Run 标识。"""

    def __init__(self) -> None:
        self.starts: list[object] = []

    def execute(self, start: object) -> object:
        self.starts.append(start)
        return SimpleNamespace(
            run=SimpleNamespace(run_id="run-001"),
            response=SimpleNamespace(text="已处理。"),
        )


def _member() -> TeamMember:
    return TeamMember.create(
        member_id="member-001",
        team_id="team-001",
        name="alice",
        role="后端开发",
        session_id="session-alice",
    )


def test_runtime_adapter_uses_existing_runtime_service_and_loop() -> None:
    runtime_service = RecordingRuntimeService()
    loop = RecordingLoop()
    executor = RuntimeTeamAgentExecutor(
        runtime_service=runtime_service,  # type: ignore[arg-type]
        loop=loop,  # type: ignore[arg-type]
    )

    execution = executor.execute(member=_member(), prompt="[Team 收件箱]\n请检查迁移。")

    assert execution.session_id == "session-alice"
    assert execution.run_id == "run-001"
    assert execution.response_text == "已处理。"
    assert len(runtime_service.events) == 1
    assert len(loop.starts) == 1


def test_runtime_adapter_validates_its_boundary() -> None:
    with pytest.raises(TypeError, match="runtime_service"):
        RuntimeTeamAgentExecutor(
            runtime_service=object(),  # type: ignore[arg-type]
            loop=RecordingLoop(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="非空字符串"):
        RuntimeTeamAgentExecutor(
            runtime_service=RecordingRuntimeService(),  # type: ignore[arg-type]
            loop=RecordingLoop(),  # type: ignore[arg-type]
        ).execute(member=_member(), prompt=" ")


def test_runtime_adapter_binds_working_directory_only_while_the_run_executes(
    tmp_path: Path,
) -> None:
    main_workspace = tmp_path / "main"
    worktree = main_workspace / ".worktrees" / "api-login"
    worktree.mkdir(parents=True)
    registry = InMemoryRunWorkingDirectoryRegistry(main_workspace=main_workspace)

    class InspectingLoop(RecordingLoop):
        def execute(self, start: object) -> object:
            context = ToolExecutionContext(
                session_id="session-alice",
                run_id="run-001",
                step_id="step-001",
            )
            assert registry.resolve(context=context) == worktree.resolve()
            return super().execute(start)

    executor = RuntimeTeamAgentExecutor(
        runtime_service=RecordingRuntimeService(),  # type: ignore[arg-type]
        loop=InspectingLoop(),  # type: ignore[arg-type]
        run_working_directory_registry=registry,
    )

    execution = executor.execute(
        member=_member(),
        prompt="[S17 自主任务]\n实现登录 API。",
        working_directory=worktree,
    )

    assert execution.run_id == "run-001"
    assert registry.resolve(
        context=ToolExecutionContext(
            session_id="session-alice",
            run_id="run-001",
            step_id="step-001",
        )
    ) == main_workspace.resolve()


def test_runtime_adapter_releases_working_directory_when_loop_raises(tmp_path: Path) -> None:
    main_workspace = tmp_path / "main"
    worktree = main_workspace / ".worktrees" / "api-login"
    worktree.mkdir(parents=True)
    registry = InMemoryRunWorkingDirectoryRegistry(main_workspace=main_workspace)

    class FailingLoop:
        def execute(self, start: object) -> object:
            raise RuntimeError("模拟执行失败")

    executor = RuntimeTeamAgentExecutor(
        runtime_service=RecordingRuntimeService(),  # type: ignore[arg-type]
        loop=FailingLoop(),  # type: ignore[arg-type]
        run_working_directory_registry=registry,
    )

    with pytest.raises(RuntimeError, match="模拟执行失败"):
        executor.execute(
            member=_member(),
            prompt="[S17 自主任务]\n实现登录 API。",
            working_directory=worktree,
        )
    assert registry.resolve(
        context=ToolExecutionContext(
            session_id="session-alice",
            run_id="run-001",
            step_id="step-001",
        )
    ) == main_workspace.resolve()
