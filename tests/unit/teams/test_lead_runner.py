from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from local_dev_agent.teams import (
    EventTeamDispatcher,
    JsonFileTeamInboxRepository,
    TeamLeadInboxRunner,
    TeamMember,
    TeamMessageDraft,
    TeamMessageType,
    TeamPromptExecution,
)
from local_dev_agent.teams.json_codec import decode_inbox
from local_dev_agent.teams.json_support import read_json_object


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class AdvancingClock:
    """以稳定递增时间记录预留与确认操作。"""

    def __init__(self) -> None:
        self._current = TIMESTAMP

    def now(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


class SequenceIdGenerator:
    """为 Lead 预留生成可断言的稳定标识。"""

    def __init__(self) -> None:
        self._next = 0

    def new_id(self, *, kind: str) -> str:
        self._next += 1
        return f"{kind}-{self._next:03d}"


class Gate:
    """记录租约占用，模拟前台或 Cron 正在使用 Lead Session。"""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.attempts = 0
        self.releases = 0

    def try_acquire(self) -> bool:
        self.attempts += 1
        return self.available

    def release(self) -> None:
        self.releases += 1


class RecordingExecutor:
    """记录 Lead 自动 Run 接收的收件箱输入。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.prompts: list[str] = []

    def execute(self, *, member: TeamMember, prompt: str) -> TeamPromptExecution:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("模拟 Lead Runtime 失败")
        return TeamPromptExecution(
            session_id=member.session_id,
            run_id="run-lead-001",
            response_text="已收到成员结果。",
        )


class StopAfterFirstWait:
    """同步接管 Runner 循环，避免测试等待真实时间。"""

    def wait(
        self,
        *,
        stop_event: Event,
        wake_event: Event,
        timeout_seconds: float,
    ) -> bool:
        stop_event.set()
        return True


class InlineThreadFactory:
    """在当前线程调用目标，方便验证注册和清理行为。"""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start(self, *, target, name: str) -> object:
        self.names.append(name)
        target()
        return object()


def _lead() -> TeamMember:
    return TeamMember.create(
        member_id="lead-001",
        team_id="team-001",
        name="lead",
        role="协调者",
        session_id="session-lead",
        created_at=TIMESTAMP,
    )


def _send_result(inbox: JsonFileTeamInboxRepository) -> None:
    inbox.send(
        TeamMessageDraft.create(
            message_id="result-message-001",
            team_id="team-001",
            sender_member_id="member-001",
            recipient_member_id="lead-001",
            message_type=TeamMessageType.RESULT,
            content="[Team 执行结果]\n迁移检查完成。",
            idempotency_key="result-001",
            created_at=TIMESTAMP,
        )
    )


def _runner(
    tmp_path: Path,
    *,
    gate: Gate,
    executor: RecordingExecutor,
    dispatcher: EventTeamDispatcher | None = None,
    waiter: object | None = None,
    thread_factory: object | None = None,
) -> TeamLeadInboxRunner:
    return TeamLeadInboxRunner(
        member=_lead(),
        inbox_repository=JsonFileTeamInboxRepository(tmp_path),
        agent_executor=executor,
        execution_gate=gate,
        id_generator=SequenceIdGenerator(),
        clock=AdvancingClock(),
        signal_registry=dispatcher or EventTeamDispatcher(),
        waiter=waiter or StopAfterFirstWait(),  # type: ignore[arg-type]
        thread_factory=thread_factory or InlineThreadFactory(),  # type: ignore[arg-type]
    )


def test_lead_runner_consumes_result_only_after_acquiring_execution_gate(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send_result(inbox)
    gate = Gate()
    executor = RecordingExecutor()

    assert _runner(tmp_path, gate=gate, executor=executor).process_once() is True

    assert gate.attempts == 1
    assert gate.releases == 1
    assert executor.prompts == [
        "[Team 收件箱]\n#1 来自 member-001（result）：[Team 执行结果]\n迁移检查完成。"
    ]
    assert inbox.list_unread(team_id="team-001", recipient_member_id="lead-001") == ()
    _, messages = decode_inbox(
        read_json_object(tmp_path / "team-001" / "inboxes" / "lead-001.json")
    )
    assert messages[0].consumed_by_session_id == "session-lead"
    assert messages[0].consumed_by_run_id == "run-lead-001"


def test_lead_runner_keeps_message_unread_when_execution_gate_is_busy(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send_result(inbox)
    gate = Gate(available=False)
    executor = RecordingExecutor()

    assert _runner(tmp_path, gate=gate, executor=executor).process_once() is False

    assert gate.attempts == 1
    assert gate.releases == 0
    assert executor.prompts == []
    assert [
        message.message_id
        for message in inbox.list_unread(
            team_id="team-001",
            recipient_member_id="lead-001",
        )
    ] == ["result-message-001"]


def test_lead_runner_releases_message_and_gate_when_runtime_fails(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send_result(inbox)
    gate = Gate()

    assert _runner(tmp_path, gate=gate, executor=RecordingExecutor(fail=True)).process_once() is False

    assert gate.releases == 1
    assert [
        message.message_id
        for message in inbox.list_unread(
            team_id="team-001",
            recipient_member_id="lead-001",
        )
    ] == ["result-message-001"]


def test_lead_runner_registers_for_dispatcher_wakeups(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send_result(inbox)
    dispatcher = EventTeamDispatcher()
    thread_factory = InlineThreadFactory()
    runner = _runner(
        tmp_path,
        gate=Gate(),
        executor=RecordingExecutor(),
        dispatcher=dispatcher,
        thread_factory=thread_factory,
    )
    wake_event = dispatcher.register(member_id="lead-001")

    dispatcher.signal(member_id="lead-001")
    assert wake_event.is_set() is True
    runner.start()

    assert thread_factory.names == ["team-lead-lead-001"]
    assert inbox.list_unread(team_id="team-001", recipient_member_id="lead-001") == ()
