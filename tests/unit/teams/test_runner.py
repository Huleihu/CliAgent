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
    TeamAutonomousWorkItem,
    TeamAutonomousWorkOutcome,
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
        self.working_directories: list[Path | None] = []

    def execute(
        self,
        *,
        member: TeamMember,
        prompt: str,
        working_directory: Path | None = None,
    ) -> TeamPromptExecution:
        self.prompts.append(prompt)
        self.working_directories.append(working_directory)
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


class RecordingAutonomousWorkSource:
    """为成员返回预设自主工作项，记录是否因收件箱优先级被调用。"""

    def __init__(self, work_item: TeamAutonomousWorkItem | None) -> None:
        self.work_item = work_item
        self.member_ids: list[str] = []

    def claim_next_work(self, *, member: TeamMember) -> TeamAutonomousWorkItem | None:
        self.member_ids.append(member.member_id)
        return self.work_item


class RecordingWorktreeDirectoryResolver:
    """按工作树名称返回预设目录，记录 Runner 是否在启动 Run 前完成解析。"""

    def __init__(self, *, main_workspace: Path, directories: dict[str, Path]) -> None:
        self.main_workspace = main_workspace
        self.directories = directories
        self.names: list[str | None] = []

    def resolve(self, *, worktree_name: str | None) -> Path:
        self.names.append(worktree_name)
        if worktree_name is None:
            return self.main_workspace
        return self.directories[worktree_name]


class RecordingAutonomousWorkVerifier:
    """返回预设核验结论，记录 Runner 是否携带正确的执行事实。"""

    def __init__(self, *, completed: bool) -> None:
        self.completed = completed
        self.calls: list[tuple[TeamAutonomousWorkItem, TeamPromptExecution | None]] = []

    def verify(
        self,
        *,
        member: TeamMember,
        work_item: TeamAutonomousWorkItem,
        execution: TeamPromptExecution | None,
    ) -> TeamAutonomousWorkOutcome:
        self.calls.append((work_item, execution))
        return TeamAutonomousWorkOutcome(
            work_item=work_item,
            execution=execution,
            completed=self.completed,
            detail=f"{member.member_id} 的核验结论。",
        )


class RecordingAutonomousResultReporter:
    """记录自主任务结论，避免 Runner 测试依赖具体收件箱格式。"""

    def __init__(self) -> None:
        self.outcomes: list[TeamAutonomousWorkOutcome] = []

    def report(self, *, member: TeamMember, outcome: TeamAutonomousWorkOutcome) -> object:
        assert member.member_id == "member-001"
        self.outcomes.append(outcome)
        return object()


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
    autonomous_work_source: object | None = None,
    autonomous_work_verifier: object | None = None,
    autonomous_result_reporter: object | None = None,
    autonomous_worktree_directory_resolver: object | None = None,
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
        autonomous_work_source=autonomous_work_source,  # type: ignore[arg-type]
        autonomous_work_verifier=autonomous_work_verifier,  # type: ignore[arg-type]
        autonomous_result_reporter=autonomous_result_reporter,  # type: ignore[arg-type]
        autonomous_worktree_directory_resolver=autonomous_worktree_directory_resolver,  # type: ignore[arg-type]
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


def test_runner_executes_claimed_autonomous_work_only_when_inbox_is_empty(tmp_path: Path) -> None:
    executor = RecordingExecutor()
    work_source = RecordingAutonomousWorkSource(
        TeamAutonomousWorkItem(
            task_id="task-api",
            subject="实现登录 API。",
            description="新增登录端点。",
        )
    )

    assert (
        _runner(
            tmp_path,
            executor=executor,
            result_reporter=FailingResultReporter(),
            autonomous_work_source=work_source,
        ).process_once()
        is True
    )

    assert work_source.member_ids == ["member-001"]
    assert executor.prompts == [
        "[S17 自主任务]\n"
        "你已成功认领项目任务：task-api\n"
        "标题：实现登录 API。\n"
        "详细要求：\n"
        "新增登录端点。\n\n"
        "请在当前工作区完成并验证该任务。\n"
        "仅当任务实际完成后，必须调用 task_complete，并传入 task_id=\"task-api\"。\n"
        "不要认领其他任务，也不要修改其他任务的归属。"
    ]
    assert JsonFileTeamInboxRepository(tmp_path).list_unread(
        team_id="team-001",
        recipient_member_id="lead-001",
    ) == ()


def test_runner_resolves_task_worktree_before_starting_autonomous_member_run(tmp_path: Path) -> None:
    main_workspace = tmp_path / "main"
    worktree = main_workspace / ".worktrees" / "api-login"
    worktree.mkdir(parents=True)
    resolver = RecordingWorktreeDirectoryResolver(
        main_workspace=main_workspace,
        directories={"api-login": worktree},
    )
    executor = RecordingExecutor()
    work_item = TeamAutonomousWorkItem(
        task_id="task-api",
        subject="实现登录 API。",
        description="",
        worktree="api-login",
    )

    assert _runner(
        tmp_path,
        executor=executor,
        autonomous_work_source=RecordingAutonomousWorkSource(work_item),
        autonomous_worktree_directory_resolver=resolver,
    ).process_once() is True

    assert resolver.names == ["api-login"]
    assert executor.working_directories == [worktree]


def test_runner_keeps_existing_inbox_work_ahead_of_autonomous_claims(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    _send(inbox)
    executor = RecordingExecutor()
    work_source = RecordingAutonomousWorkSource(
        TeamAutonomousWorkItem(
            task_id="task-api",
            subject="实现登录 API。",
            description="",
        )
    )

    assert _runner(
        tmp_path,
        executor=executor,
        autonomous_work_source=work_source,
    ).process_once() is True

    assert work_source.member_ids == []
    assert executor.prompts == [
        "[Team 收件箱]\n#1 来自 lead-001（assignment）：检查数据库迁移。"
    ]


def test_runner_does_not_execute_a_model_run_when_no_autonomous_work_is_claimed(
    tmp_path: Path,
) -> None:
    executor = RecordingExecutor()
    work_source = RecordingAutonomousWorkSource(None)

    assert _runner(
        tmp_path,
        executor=executor,
        autonomous_work_source=work_source,
    ).process_once() is False

    assert work_source.member_ids == ["member-001"]
    assert executor.prompts == []


def test_runner_reports_only_the_verifier_completion_outcome_for_autonomous_work(
    tmp_path: Path,
) -> None:
    work_item = TeamAutonomousWorkItem(
        task_id="task-api",
        subject="实现登录 API。",
        description="",
    )
    verifier = RecordingAutonomousWorkVerifier(completed=True)
    reporter = RecordingAutonomousResultReporter()

    assert _runner(
        tmp_path,
        executor=RecordingExecutor(),
        autonomous_work_source=RecordingAutonomousWorkSource(work_item),
        autonomous_work_verifier=verifier,
        autonomous_result_reporter=reporter,
    ).process_once() is True

    assert verifier.calls[0][0] is work_item
    assert verifier.calls[0][1] is not None
    assert reporter.outcomes[0].completed is True


def test_runner_reports_a_failed_outcome_when_autonomous_run_raises(tmp_path: Path) -> None:
    work_item = TeamAutonomousWorkItem(
        task_id="task-api",
        subject="实现登录 API。",
        description="",
    )
    verifier = RecordingAutonomousWorkVerifier(completed=False)
    reporter = RecordingAutonomousResultReporter()

    assert _runner(
        tmp_path,
        executor=RecordingExecutor(fail=True),
        autonomous_work_source=RecordingAutonomousWorkSource(work_item),
        autonomous_work_verifier=verifier,
        autonomous_result_reporter=reporter,
    ).process_once() is False

    assert verifier.calls == [(work_item, None)]
    assert reporter.outcomes[0].completed is False


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


def test_runner_rejects_an_invalid_autonomous_work_source(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)

    with pytest.raises(TypeError, match="autonomous_work_source 必须提供"):
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
            autonomous_work_source=object(),  # type: ignore[arg-type]
        )


def test_runner_requires_autonomous_verifier_and_reporter_to_be_configured_together(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)

    with pytest.raises(ValueError, match="必须同时配置"):
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
            autonomous_work_verifier=RecordingAutonomousWorkVerifier(completed=True),
        )


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
    work_source = RecordingAutonomousWorkSource(
        TeamAutonomousWorkItem(
            task_id="task-api",
            subject="实现登录 API。",
            description="",
        )
    )
    runner = _runner(
        tmp_path,
        executor=executor,
        protocol_dispatcher=coordinator,
        autonomous_work_source=work_source,
    )

    assert runner.process_once() is True

    assert executor.prompts == []
    assert work_source.member_ids == []
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
