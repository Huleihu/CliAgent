from types import SimpleNamespace

import pytest

from local_dev_agent.teams import RuntimeTeamAgentExecutor, TeamMember


class RecordingRuntimeService:
    """记录 Team 适配器提交给标准 Runtime 的输入事件。"""

    def __init__(self) -> None:
        self.events: list[object] = []

    def handle(self, event: object) -> object:
        self.events.append(event)
        return object()


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
