from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from local_dev_agent.teams import (
    EventTeamDispatcher,
    JsonFileTeamInboxRepository,
    JsonFileTeamProtocolStateRepository,
    TeamLeadInboxRunner,
    TeamMember,
    TeamMessageDraft,
    TeamMessageType,
    TeamProtocolCoordinator,
    TeamProtocolDecision,
    TeamProtocolState,
    TeamProtocolStatus,
    TeamProtocolType,
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


class RecordingCompletionSink:
    """记录已经成功确认收件箱后的 Lead 自动响应。"""

    def __init__(self) -> None:
        self.executions: list[TeamPromptExecution] = []

    def __call__(self, execution: TeamPromptExecution) -> None:
        self.executions.append(execution)


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
    completion_sink: object | None = None,
    protocol_dispatcher: object | None = None,
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
        on_execution_completed=completion_sink,  # type: ignore[arg-type]
        protocol_dispatcher=protocol_dispatcher,  # type: ignore[arg-type]
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


def test_lead_runner_notifies_completion_after_acknowledging_message(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send_result(inbox)
    completion_sink = RecordingCompletionSink()

    assert (
        _runner(
            tmp_path,
            gate=Gate(),
            executor=RecordingExecutor(),
            completion_sink=completion_sink,
        ).process_once()
        is True
    )

    assert [execution.response_text for execution in completion_sink.executions] == ["已收到成员结果。"]
    assert inbox.list_unread(team_id="team-001", recipient_member_id="lead-001") == ()


def test_lead_runner_matches_shutdown_response_without_runtime_or_execution_gate(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
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
    response = coordinator.send_response(
        request_id=shutdown.request_id,
        sender_member_id="member-001",
        decision=TeamProtocolDecision.APPROVED,
        content="成员已安全停止。",
        message_id="shutdown-response-001",
        idempotency_key="protocol:shutdown-response-001",
    )
    gate = Gate(available=False)
    executor = RecordingExecutor()

    assert (
        _runner(
            tmp_path,
            gate=gate,
            executor=executor,
            protocol_dispatcher=coordinator,
        ).process_once()
        is True
    )

    assert response.message_id == "shutdown-response-001"
    assert executor.prompts == []
    assert gate.attempts == 0
    persisted_state = JsonFileTeamProtocolStateRepository(tmp_path).get(shutdown.request_id)
    assert persisted_state is not None
    assert persisted_state.status is TeamProtocolStatus.APPROVED
    assert inbox.list_unread(team_id="team-001", recipient_member_id="lead-001") == ()


def test_lead_runner_forwards_plan_request_to_runtime_after_protocol_validation(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    coordinator = TeamProtocolCoordinator(
        state_repository=JsonFileTeamProtocolStateRepository(tmp_path),
        inbox_repository=inbox,
        clock=AdvancingClock(),
    )
    plan_request = TeamProtocolState.create(
        request_id="plan-001",
        team_id="team-001",
        protocol_type=TeamProtocolType.PLAN_APPROVAL,
        sender_member_id="member-001",
        target_member_id="lead-001",
        payload="先补充认证适配器测试，再迁移调用方。",
        created_at=TIMESTAMP,
    )
    coordinator.open_request(
        state=plan_request,
        message_id="plan-request-001",
        idempotency_key="protocol:plan-request-001",
    )
    gate = Gate()
    executor = RecordingExecutor()

    assert (
        _runner(
            tmp_path,
            gate=gate,
            executor=executor,
            protocol_dispatcher=coordinator,
        ).process_once()
        is True
    )

    assert gate.attempts == 1
    assert gate.releases == 1
    assert executor.prompts == [
        "[Team 收件箱]\n#1 来自 member-001（plan_approval_request）："
        "先补充认证适配器测试，再迁移调用方。"
    ]
    persisted_state = JsonFileTeamProtocolStateRepository(tmp_path).get(plan_request.request_id)
    assert persisted_state is not None
    assert persisted_state.status is TeamProtocolStatus.PENDING
