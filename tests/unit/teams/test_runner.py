from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest

from local_dev_agent.teams import (
    EventTeamDispatcher,
    InboxTeamResultReporter,
    JsonFileTeamInboxRepository,
    JsonFileTeamProtocolStateRepository,
    TeamMember,
    TeamMemberRunner,
    TeamMessageDraft,
    TeamMessageType,
    TeamProtocolCoordinator,
    TeamProtocolState,
    TeamProtocolType,
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


class FailingResultReporter:
    """模拟结果持久化失败，验证原任务消息仍可重投。"""

    def report(self, **_: object) -> tuple[object, ...]:
        raise RuntimeError("模拟结果回传失败")


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
    result_reporter: object | None = None,
    waiter: object | None = None,
    thread_factory: object | None = None,
    protocol_dispatcher: object | None = None,
) -> TeamMemberRunner:
    dispatcher = EventTeamDispatcher()
    inbox = JsonFileTeamInboxRepository(tmp_path)
    return TeamMemberRunner(
        member=_member(),
        inbox_repository=inbox,
        agent_executor=executor,
        result_reporter=result_reporter or InboxTeamResultReporter(
            inbox_repository=inbox,
            clock=AdvancingClock(),
            dispatcher=dispatcher,
        ),
        id_generator=SequenceIdGenerator(),
        clock=AdvancingClock(),
        signal_registry=dispatcher,
        waiter=waiter or StopAfterFirstWait(),  # type: ignore[arg-type]
        thread_factory=thread_factory or InlineThreadFactory(),  # type: ignore[arg-type]
        protocol_dispatcher=protocol_dispatcher,  # type: ignore[arg-type]
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
    reports = inbox.list_unread(team_id="team-001", recipient_member_id="lead-001")
    assert len(reports) == 1
    assert reports[0].message_type is TeamMessageType.RESULT
    assert reports[0].sender_member_id == "member-001"
    assert reports[0].content.endswith("已处理。")
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
            result_reporter=InboxTeamResultReporter(
                inbox_repository=inbox,
                clock=AdvancingClock(),
                dispatcher=EventTeamDispatcher(),
            ),
            id_generator=SequenceIdGenerator(),
            clock=AdvancingClock(),
            signal_registry=EventTeamDispatcher(),
            waiter=StopAfterFirstWait(),
            thread_factory=InlineThreadFactory(),  # type: ignore[arg-type]
            batch_size=0,
        )


def test_runner_releases_assignment_when_result_reporting_fails(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send(inbox)

    assert (
        _runner(
            tmp_path,
            executor=RecordingExecutor(),
            result_reporter=FailingResultReporter(),
        ).process_once()
        is False
    )
    assert [
        message.message_id
        for message in inbox.list_unread(
            team_id="team-001",
            recipient_member_id="member-001",
        )
    ] == ["message-001"]


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
        result_reporter=InboxTeamResultReporter(
            inbox_repository=inbox,
            clock=AdvancingClock(),
            dispatcher=dispatcher,
        ),
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


def test_member_runner_confirms_shutdown_without_runtime_and_releases_earlier_work(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send(inbox)
    coordinator = TeamProtocolCoordinator(
        state_repository=JsonFileTeamProtocolStateRepository(tmp_path),
        inbox_repository=inbox,
        clock=AdvancingClock(),
    )
    shutdown = TeamProtocolState.create(
        request_id="shutdown-001",
        team_id="team-001",
        protocol_type=TeamProtocolType.SHUTDOWN,
        sender_member_id="lead-001",
        target_member_id="member-001",
        payload="请安全停止。",
        created_at=TIMESTAMP,
    )
    coordinator.open_request(
        state=shutdown,
        message_id="shutdown-request-001",
        idempotency_key="protocol:shutdown-request-001",
    )
    executor = RecordingExecutor()
    runner = _runner(tmp_path, executor=executor, protocol_dispatcher=coordinator)

    assert runner.process_once() is True

    assert executor.prompts == []
    assert runner._stop_event.is_set() is True
    assert [
        message.message_id
        for message in inbox.list_unread(
            team_id="team-001",
            recipient_member_id="member-001",
        )
    ] == ["message-001"]
    responses = inbox.list_unread(team_id="team-001", recipient_member_id="lead-001")
    assert len(responses) == 1
    assert responses[0].message_type is TeamMessageType.SHUTDOWN_RESPONSE
    _, member_messages = decode_inbox(
        read_json_object(tmp_path / "team-001" / "inboxes" / "member-001.json")
    )
    assert member_messages[1].consumed_by_run_id == "protocol-dispatch-shutdown-request-001"
