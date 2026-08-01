from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_dev_agent.teams import (
    JsonFileTeamAssignmentRepository,
    JsonFileTeamInboxRepository,
    JsonFileTeamMemberRepository,
    JsonFileTeamRepository,
    TeamAssignmentStatus,
    TeamService,
)


class SequentialIdGenerator:
    def __init__(self) -> None:
        self._count = 0

    def new_id(self, *, kind: str) -> str:
        self._count += 1
        return f"{kind}-{self._count:03d}"


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


class RecordingDispatcher:
    def __init__(self) -> None:
        self.member_ids: list[str] = []

    def signal(self, *, member_id: str) -> None:
        self.member_ids.append(member_id)


def _service(tmp_path: Path) -> tuple[TeamService, RecordingDispatcher]:
    dispatcher = RecordingDispatcher()
    return (
        TeamService(
            team_repository=JsonFileTeamRepository(tmp_path),
            member_repository=JsonFileTeamMemberRepository(tmp_path),
            assignment_repository=JsonFileTeamAssignmentRepository(tmp_path),
            inbox_repository=JsonFileTeamInboxRepository(tmp_path),
            id_generator=SequentialIdGenerator(),
            clock=FakeClock(),
            dispatcher=dispatcher,
        ),
        dispatcher,
    )


def test_service_keeps_assignment_snapshot_separate_from_delivery_and_only_signals_runner(
    tmp_path: Path,
) -> None:
    service, dispatcher = _service(tmp_path)
    team, lead = service.create_team(
        workspace_id="workspace-001",
        lead_name="lead",
        lead_role="协调者",
        lead_session_id="session-lead",
    )
    teammate = service.add_teammate(
        team_id=team.team_id,
        name="alice",
        role="后端开发",
        session_id="session-alice",
    )

    assignment = service.assign_work(
        team_id=team.team_id,
        assigned_by_member_id=lead.member_id,
        assignee_member_id=teammate.member_id,
        prompt="检查数据库迁移。",
        project_task_id="project-task-001",
    )

    inbox = JsonFileTeamInboxRepository(tmp_path)
    messages = inbox.list_unread(
        team_id=team.team_id,
        recipient_member_id=teammate.member_id,
    )
    assert assignment.project_task_id == "project-task-001"
    assert assignment.status is TeamAssignmentStatus.PENDING
    assert [message.content for message in messages] == ["检查数据库迁移。"]
    assert dispatcher.member_ids == [teammate.member_id]


def test_service_recovery_releases_messages_and_marks_interrupted_assignment_without_run(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    team, lead = service.create_team(
        workspace_id="workspace-001",
        lead_name="lead",
        lead_role="协调者",
        lead_session_id="session-lead",
    )
    teammate = service.add_teammate(
        team_id=team.team_id,
        name="alice",
        role="后端开发",
        session_id="session-alice",
    )
    assignment = service.assign_work(
        team_id=team.team_id,
        assigned_by_member_id=lead.member_id,
        assignee_member_id=teammate.member_id,
        prompt="检查数据库迁移。",
    )
    assignments = JsonFileTeamAssignmentRepository(tmp_path)
    assignments.replace(
        assignment.start(
            run_id="run-interrupted",
            occurred_at=datetime(2026, 8, 1, 8, 5, tzinfo=timezone.utc),
        )
    )
    inbox = JsonFileTeamInboxRepository(tmp_path)
    reservation = inbox.reserve_unread(
        team_id=team.team_id,
        recipient_member_id=teammate.member_id,
        reservation_id="reservation-001",
        reserved_at=datetime(2026, 8, 1, 8, 5, tzinfo=timezone.utc),
        limit=10,
    )

    assert reservation is not None
    recovered = service.recover_team(team_id=team.team_id)

    assert [message.message_id for message in recovered.released_messages] == [
        reservation.messages[0].message_id
    ]
    assert recovered.recovery_pending_assignments[0].status is TeamAssignmentStatus.RECOVERY_PENDING
    assert inbox.list_unread(
        team_id=team.team_id,
        recipient_member_id=teammate.member_id,
    )[0].message_id == reservation.messages[0].message_id
