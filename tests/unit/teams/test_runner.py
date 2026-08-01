from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest

from local_dev_agent.teams import (
    EventTeamDispatcher,
    JsonFileTeamInboxRepository,
    TeamMember,
    TeamMemberRunner,
    TeamMessageDraft,
    TeamMessageType,
    TeamPromptExecution,
)
from local_dev_agent.teams.json_codec import decode_inbox
from local_dev_agent.teams.json_support import read_json_object


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class AdvancingClock:
    """以固定增量返回时间，避免测试依赖真实时钟。"""

    def __init__(self) -> None:
        self._current = TIMESTAMP

    def now(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


class SequenceIdGenerator:
    """为每次预留生成可断言的稳定标识。"""

    def __init__(self) -> None:
        self._next = 0

    def new_id(self, *, kind: str) -> str:
        self._next += 1
        return f"{kind}-{self._next:03d}"


class RecordingExecutor:
    """记录 Runner 交给既有 Runtime 端口的输入。"""

    def __init__(self, *, session_id: str = "session-alice", fail: bool = False) -> None:
        self.session_id = session_id
        self.fail = fail
        self.prompts: list[str] = []

    def execute(self, *, member: TeamMember, prompt: str) -> TeamPromptExecution:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("模拟 Runtime 失败")
        return TeamPromptExecution(
            session_id=self.session_id,
            run_id="run-001",
            response_text="已处理。",
        )


class StopAfterFirstWait:
    """第一次等待即停止循环，验证线程目标无需真实 sleep。"""

    def __init__(self) -> None:
        self.calls = 0

    def wait(
        self,
        *,
        stop_event: Event,
        wake_event: Event,
        timeout_seconds: float,
    ) -> bool:
        self.calls += 1
        stop_event.set()
        return True


class InlineThreadFactory:
    """同步运行线程目标，使后台 Runner 的测试没有线程竞速。"""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start(self, *, target, name: str) -> object:
        self.names.append(name)
        target()
        return object()


def _member() -> TeamMember:
    return TeamMember.create(
        member_id="member-001",
        team_id="team-001",
        name="alice",
        role="后端开发",
        session_id="session-alice",
        created_at=TIMESTAMP,
    )


def _send(inbox: JsonFileTeamInboxRepository) -> None:
    inbox.send(
        TeamMessageDraft.create(
            message_id="message-001",
            team_id="team-001",
            sender_member_id="lead-001",
            recipient_member_id="member-001",
            message_type=TeamMessageType.ASSIGNMENT,
            content="检查数据库迁移。",
            idempotency_key="key-001",
            created_at=TIMESTAMP,
        )
    )


def _runner(
    tmp_path: Path,
    *,
    executor: RecordingExecutor,
    waiter: object | None = None,
    thread_factory: object | None = None,
) -> TeamMemberRunner:
    return TeamMemberRunner(
        member=_member(),
        inbox_repository=JsonFileTeamInboxRepository(tmp_path),
        agent_executor=executor,
        id_generator=SequenceIdGenerator(),
        clock=AdvancingClock(),
        signal_registry=EventTeamDispatcher(),
        waiter=waiter or StopAfterFirstWait(),  # type: ignore[arg-type]
        thread_factory=thread_factory or InlineThreadFactory(),  # type: ignore[arg-type]
    )


def test_runner_reserves_executes_and_acknowledges_messages_only_after_runtime_success(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send(inbox)
    executor = RecordingExecutor()

    assert _runner(tmp_path, executor=executor).process_once() is True

    assert executor.prompts == ["[Team 收件箱]\n#1 来自 lead-001（assignment）：检查数据库迁移。"]
    assert inbox.list_unread(team_id="team-001", recipient_member_id="member-001") == ()
    _, messages = decode_inbox(
        read_json_object(tmp_path / "team-001" / "inboxes" / "member-001.json")
    )
    assert messages[0].consumed_by_session_id == "session-alice"
    assert messages[0].consumed_by_run_id == "run-001"


def test_runner_releases_reserved_messages_when_runtime_fails(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send(inbox)

    assert _runner(tmp_path, executor=RecordingExecutor(fail=True)).process_once() is False
    assert [message.message_id for message in inbox.list_unread(
        team_id="team-001",
        recipient_member_id="member-001",
    )] == ["message-001"]

    with pytest.raises(ValueError, match="正整数"):
        TeamMemberRunner(
            member=_member(),
            inbox_repository=inbox,
            agent_executor=RecordingExecutor(),
            id_generator=SequenceIdGenerator(),
            clock=AdvancingClock(),
            signal_registry=EventTeamDispatcher(),
            waiter=StopAfterFirstWait(),
            thread_factory=InlineThreadFactory(),  # type: ignore[arg-type]
            batch_size=0,
        )


def test_runner_and_dispatcher_use_injected_event_waiter_and_thread_factory(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send(inbox)
    dispatcher = EventTeamDispatcher()
    executor = RecordingExecutor()
    waiter = StopAfterFirstWait()
    thread_factory = InlineThreadFactory()
    runner = TeamMemberRunner(
        member=_member(),
        inbox_repository=inbox,
        agent_executor=executor,
        id_generator=SequenceIdGenerator(),
        clock=AdvancingClock(),
        signal_registry=dispatcher,
        waiter=waiter,
        thread_factory=thread_factory,  # type: ignore[arg-type]
    )
    wake_event = dispatcher.register(member_id="member-001")

    dispatcher.signal(member_id="member-001")
    assert wake_event.is_set() is True
    runner.start()

    assert executor.prompts
    assert waiter.calls == 1
    assert thread_factory.names == ["team-member-member-001"]
    with pytest.raises(RuntimeError, match="已启动"):
        runner.start()
