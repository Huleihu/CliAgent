from datetime import datetime, timezone

from local_dev_agent.teams import (
    InboxReservation,
    Team,
    TeamAgentExecutor,
    TeamAutonomousResultReporter,
    TeamAutonomousWorkItem,
    TeamAutonomousWorkOutcome,
    TeamAutonomousWorkSource,
    TeamAssignment,
    TeamAssignmentRepository,
    TeamClock,
    TeamDispatcher,
    TeamExecutionGate,
    TeamIdGenerator,
    TeamInboxRepository,
    TeamMember,
    TeamMemberRepository,
    TeamMessage,
    TeamMessageDraft,
    TeamMessageType,
    TeamPromptExecution,
    TeamProtocolState,
    TeamProtocolStateRepository,
    TeamProtocolStatus,
    TeamProtocolType,
    TeamRepository,
    TeamResultReporter,
)


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class FixedIdGenerator:
    def new_id(self, *, kind: str) -> str:
        return f"{kind}-001"


class FixedClock:
    def now(self) -> datetime:
        return TIMESTAMP


class InMemoryTeamRepository:
    def __init__(self) -> None:
        self.teams: dict[str, Team] = {}

    def add(self, team: Team) -> Team:
        self.teams[team.team_id] = team
        return team

    def get(self, team_id: str) -> Team | None:
        return self.teams.get(team_id)

    def replace(self, team: Team) -> Team:
        self.teams[team.team_id] = team
        return team


class InMemoryMemberRepository:
    def __init__(self) -> None:
        self.members: dict[str, TeamMember] = {}

    def add(self, member: TeamMember) -> TeamMember:
        self.members[member.member_id] = member
        return member

    def get(self, member_id: str) -> TeamMember | None:
        return self.members.get(member_id)

    def list_for_team(self, team_id: str) -> tuple[TeamMember, ...]:
        return tuple(member for member in self.members.values() if member.team_id == team_id)

    def replace(self, member: TeamMember) -> TeamMember:
        self.members[member.member_id] = member
        return member


class InMemoryAssignmentRepository:
    def __init__(self) -> None:
        self.assignments: dict[str, TeamAssignment] = {}

    def add(self, assignment: TeamAssignment) -> TeamAssignment:
        self.assignments[assignment.assignment_id] = assignment
        return assignment

    def get(self, assignment_id: str) -> TeamAssignment | None:
        return self.assignments.get(assignment_id)

    def list_for_team(self, team_id: str) -> tuple[TeamAssignment, ...]:
        return tuple(
            assignment
            for assignment in self.assignments.values()
            if assignment.team_id == team_id
        )

    def list_for_assignee(self, member_id: str) -> tuple[TeamAssignment, ...]:
        return tuple(
            assignment
            for assignment in self.assignments.values()
            if assignment.assignee_member_id == member_id
        )

    def replace(self, assignment: TeamAssignment) -> TeamAssignment:
        self.assignments[assignment.assignment_id] = assignment
        return assignment


class InMemoryInboxRepository:
    def send(self, draft: TeamMessageDraft) -> TeamMessage:
        return TeamMessage.create(
            message_id=draft.message_id,
            team_id=draft.team_id,
            sender_member_id=draft.sender_member_id,
            recipient_member_id=draft.recipient_member_id,
            sequence=1,
            message_type=draft.message_type,
            content=draft.content,
            idempotency_key=draft.idempotency_key,
            created_at=draft.created_at,
        )

    def list_unread(self, *, team_id: str, recipient_member_id: str) -> tuple[TeamMessage, ...]:
        return ()

    def reserve_unread(
        self,
        *,
        team_id: str,
        recipient_member_id: str,
        reservation_id: str,
        reserved_at: datetime,
        limit: int,
    ) -> InboxReservation | None:
        return None

    def acknowledge(
        self,
        reservation: InboxReservation,
        *,
        consumer_session_id: str,
        consumer_run_id: str,
        consumed_at: datetime,
    ) -> tuple[TeamMessage, ...]:
        return ()

    def release(self, reservation: InboxReservation) -> tuple[TeamMessage, ...]:
        return ()

    def recover_reserved(self, *, team_id: str) -> tuple[TeamMessage, ...]:
        return ()


class RecordingDispatcher:
    def __init__(self) -> None:
        self.member_ids: list[str] = []

    def signal(self, *, member_id: str) -> None:
        self.member_ids.append(member_id)


class FixedAgentExecutor:
    def execute(self, *, member: TeamMember, prompt: str) -> TeamPromptExecution:
        return TeamPromptExecution(
            session_id=member.session_id,
            run_id="run-001",
            response_text=prompt,
        )


class FixedAutonomousWorkSource:
    def claim_next_work(self, *, member: TeamMember) -> TeamAutonomousWorkItem | None:
        return TeamAutonomousWorkItem(
            task_id="task-001",
            subject="实现自主认领。",
            description="",
        )


class RecordingResultReporter:
    def report(self, *, member, source_messages, execution) -> tuple[TeamMessage, ...]:
        return ()


class RecordingAutonomousResultReporter:
    def report(self, *, member, outcome) -> TeamMessage:
        return TeamMessage.create(
            message_id="result-001",
            team_id=member.team_id,
            sender_member_id=member.member_id,
            recipient_member_id="lead-001",
            sequence=1,
            message_type=TeamMessageType.RESULT,
            content=outcome.detail,
            idempotency_key="result-001",
            created_at=TIMESTAMP,
        )


class Gate:
    def try_acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None


class InMemoryProtocolStateRepository:
    def __init__(self) -> None:
        self.states: dict[str, TeamProtocolState] = {}

    def add(self, state: TeamProtocolState) -> TeamProtocolState:
        self.states[state.request_id] = state
        return state

    def get(self, request_id: str) -> TeamProtocolState | None:
        return self.states.get(request_id)

    def list_pending_for_team(self, team_id: str) -> tuple[TeamProtocolState, ...]:
        return tuple(
            state
            for state in self.states.values()
            if state.team_id == team_id and state.status is TeamProtocolStatus.PENDING
        )

    def replace(self, state: TeamProtocolState) -> TeamProtocolState:
        self.states[state.request_id] = state
        return state


def test_team_ports_accept_structural_implementations() -> None:
    id_generator: TeamIdGenerator = FixedIdGenerator()
    clock: TeamClock = FixedClock()
    team_repository: TeamRepository = InMemoryTeamRepository()
    member_repository: TeamMemberRepository = InMemoryMemberRepository()
    assignment_repository: TeamAssignmentRepository = InMemoryAssignmentRepository()
    inbox_repository: TeamInboxRepository = InMemoryInboxRepository()
    dispatcher: TeamDispatcher = RecordingDispatcher()
    executor: TeamAgentExecutor = FixedAgentExecutor()
    autonomous_work_source: TeamAutonomousWorkSource = FixedAutonomousWorkSource()
    result_reporter: TeamResultReporter = RecordingResultReporter()
    autonomous_result_reporter: TeamAutonomousResultReporter = (
        RecordingAutonomousResultReporter()
    )
    execution_gate: TeamExecutionGate = Gate()
    protocol_repository: TeamProtocolStateRepository = InMemoryProtocolStateRepository()

    member = TeamMember.create(
        member_id="member-001",
        team_id="team-001",
        name="alice",
        role="开发",
        session_id="session-001",
        created_at=clock.now(),
    )
    team = Team.create(
        team_id="team-001",
        workspace_id="workspace-001",
        lead_member_id="member-001",
        created_at=clock.now(),
    )
    assignment = TeamAssignment.create(
        assignment_id="assignment-001",
        team_id=team.team_id,
        assigned_by_member_id="member-001",
        assignee_member_id=member.member_id,
        prompt="检查测试。",
        created_at=clock.now(),
    )

    assert id_generator.new_id(kind="message") == "message-001"
    assert team_repository.add(team) is team
    assert member_repository.add(member) is member
    assert assignment_repository.add(assignment) is assignment
    assert inbox_repository.list_unread(
        team_id=team.team_id,
        recipient_member_id=member.member_id,
    ) == ()
    dispatcher.signal(member_id=member.member_id)
    assert dispatcher.member_ids == ["member-001"]  # type: ignore[attr-defined]
    assert executor.execute(member=member, prompt="继续处理。").run_id == "run-001"
    work_item = autonomous_work_source.claim_next_work(member=member)
    assert work_item is not None
    assert work_item.task_id == "task-001"
    assert result_reporter.report(member=member, source_messages=(), execution=executor.execute(member=member, prompt="继续处理。")) == ()
    outcome = TeamAutonomousWorkOutcome(
        work_item=work_item,
        execution=None,
        completed=False,
        detail="成员尚未执行。",
    )
    assert autonomous_result_reporter.report(member=member, outcome=outcome).message_id == "result-001"
    assert execution_gate.try_acquire() is True
    assert execution_gate.release() is None
    protocol_state = TeamProtocolState.create(
        request_id="request-001",
        team_id=team.team_id,
        protocol_type=TeamProtocolType.SHUTDOWN,
        sender_member_id=team.lead_member_id,
        target_member_id="member-002",
        payload="请安全停止当前 Runner。",
        created_at=clock.now(),
    )
    assert protocol_repository.add(protocol_state) is protocol_state
    assert protocol_repository.get(protocol_state.request_id) is protocol_state
    assert protocol_repository.list_pending_for_team(team.team_id) == (protocol_state,)
