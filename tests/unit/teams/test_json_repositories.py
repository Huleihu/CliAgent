from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from local_dev_agent.teams import (
    JsonFileTeamAssignmentRepository,
    JsonFileTeamInboxRepository,
    JsonFileTeamMemberRepository,
    JsonFileTeamRepository,
    Team,
    TeamAssignment,
    TeamMember,
    TeamMessageDeliveryStatus,
    TeamMessageDraft,
    TeamMessageType,
    TeamProtocolDecision,
)
from local_dev_agent.teams.errors import TeamMessageIdempotencyConflictError
from local_dev_agent.teams.json_support import write_json_atomically


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


def _draft(
    *,
    message_id: str,
    idempotency_key: str,
    content: str = "请检查数据库迁移。",
    created_at: datetime = TIMESTAMP,
) -> TeamMessageDraft:
    return TeamMessageDraft.create(
        message_id=message_id,
        team_id="team-001",
        sender_member_id="lead-001",
        recipient_member_id="member-001",
        message_type=TeamMessageType.PLAIN,
        content=content,
        idempotency_key=idempotency_key,
        created_at=created_at,
    )


def test_json_repositories_round_trip_separate_team_member_and_assignment_snapshots(
    tmp_path: Path,
) -> None:
    teams = JsonFileTeamRepository(tmp_path)
    members = JsonFileTeamMemberRepository(tmp_path)
    assignments = JsonFileTeamAssignmentRepository(tmp_path)
    team = Team.create(
        team_id="team-001",
        workspace_id="workspace-001",
        lead_member_id="lead-001",
        created_at=TIMESTAMP,
    )
    assignment = TeamAssignment.create(
        assignment_id="assignment-001",
        team_id=team.team_id,
        assigned_by_member_id="lead-001",
        assignee_member_id="member-001",
        prompt="检查数据库迁移。",
        project_task_id="project-task-001",
        created_at=TIMESTAMP,
    )

    teams.add(team)
    members.add(
        TeamMember.create(
            member_id="member-001",
            team_id=team.team_id,
            name="alice",
            role="后端开发",
            session_id="session-001",
            created_at=TIMESTAMP,
        )
    )
    assignments.add(assignment)

    assert JsonFileTeamRepository(tmp_path).get(team.team_id) == team
    assert [member.member_id for member in members.list_for_team(team.team_id)] == [
        "member-001"
    ]
    assert assignments.list_for_assignee("member-001") == (assignment,)
    assert assignments.get(assignment.assignment_id) == assignment


def test_inbox_allocates_sequence_idempotently_and_acknowledges_reserved_messages(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    first_draft = _draft(message_id="message-001", idempotency_key="key-001")
    first = inbox.send(first_draft)
    repeated = inbox.send(first_draft)
    second = inbox.send(
        _draft(
            message_id="message-002",
            idempotency_key="key-002",
            created_at=TIMESTAMP + timedelta(seconds=1),
        )
    )

    assert first.sequence == 1
    assert repeated == first
    assert second.sequence == 2
    with pytest.raises(TeamMessageIdempotencyConflictError):
        inbox.send(
            _draft(
                message_id="message-conflict",
                idempotency_key="key-001",
                content="不同的内容。",
            )
        )

    reservation = inbox.reserve_unread(
        team_id="team-001",
        recipient_member_id="member-001",
        reservation_id="reservation-001",
        reserved_at=TIMESTAMP + timedelta(seconds=2),
        limit=1,
    )

    assert reservation is not None
    consumed = inbox.acknowledge(
        reservation,
        consumer_session_id="session-001",
        consumer_run_id="run-001",
        consumed_at=TIMESTAMP + timedelta(seconds=3),
    )
    assert consumed[0].delivery_status is TeamMessageDeliveryStatus.CONSUMED
    assert JsonFileTeamInboxRepository(tmp_path).list_unread(
        team_id="team-001",
        recipient_member_id="member-001",
    ) == (second,)


def test_recover_reserved_releases_only_messages_left_by_an_interrupted_worker(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    first = inbox.send(_draft(message_id="message-001", idempotency_key="key-001"))
    second = inbox.send(
        _draft(
            message_id="message-002",
            idempotency_key="key-002",
            created_at=TIMESTAMP + timedelta(seconds=1),
        )
    )
    reservation = inbox.reserve_unread(
        team_id="team-001",
        recipient_member_id="member-001",
        reservation_id="reservation-001",
        reserved_at=TIMESTAMP + timedelta(seconds=2),
        limit=1,
    )

    assert reservation is not None
    assert reservation.messages == (
        first.reserve(
            reservation_id="reservation-001",
            occurred_at=TIMESTAMP + timedelta(seconds=2),
        ),
    )
    recovered = inbox.recover_reserved(team_id="team-001")

    assert tuple(message.message_id for message in recovered) == ("message-001",)
    assert tuple(
        message.message_id
        for message in inbox.list_unread(
            team_id="team-001",
            recipient_member_id="member-001",
        )
    ) == (first.message_id, second.message_id)


def test_inbox_persists_protocol_fields_and_recovers_them_across_instances(
    tmp_path: Path,
) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)

    sent = inbox.send(
        TeamMessageDraft.create(
            message_id="response-001",
            team_id="team-001",
            sender_member_id="lead-001",
            recipient_member_id="member-001",
            message_type=TeamMessageType.SHUTDOWN_RESPONSE,
            content="已安全停止。",
            idempotency_key="protocol:response-001",
            request_id="request-001",
            protocol_decision=TeamProtocolDecision.APPROVED,
            created_at=TIMESTAMP,
        )
    )

    restored = JsonFileTeamInboxRepository(tmp_path).list_unread(
        team_id="team-001",
        recipient_member_id="member-001",
    )

    assert restored == (sent,)
    assert restored[0].request_id == "request-001"
    assert restored[0].protocol_decision is TeamProtocolDecision.APPROVED


def test_inbox_decodes_legacy_s15_message_without_protocol_fields(tmp_path: Path) -> None:
    write_json_atomically(
        tmp_path / "team-001" / "inboxes" / "member-001.json",
        {
            "entity_type": "team_inbox",
            "schema_version": 1,
            "data": {
                "next_sequence": 2,
                "messages": [
                    {
                        "message_id": "message-001",
                        "team_id": "team-001",
                        "sender_member_id": "lead-001",
                        "recipient_member_id": "member-001",
                        "sequence": 1,
                        "message_type": "assignment",
                        "content": "检查数据库迁移。",
                        "idempotency_key": "assignment-001",
                        "created_at": TIMESTAMP.isoformat(),
                        "delivery_status": "unread",
                        "reservation_id": None,
                        "reserved_at": None,
                        "consumed_by_session_id": None,
                        "consumed_by_run_id": None,
                        "consumed_at": None,
                    }
                ],
            },
        },
    )

    restored = JsonFileTeamInboxRepository(tmp_path).list_unread(
        team_id="team-001",
        recipient_member_id="member-001",
    )

    assert restored[0].request_id is None
    assert restored[0].protocol_decision is None
