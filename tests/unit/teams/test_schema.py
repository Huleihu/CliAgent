from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.teams import (
    InboxReservation,
    Team,
    TeamAssignment,
    TeamAssignmentStatus,
    TeamMember,
    TeamMessage,
    TeamMessageDeliveryStatus,
    TeamMessageType,
    TeamPromptExecution,
)
from local_dev_agent.teams.errors import (
    InvalidTeamAssignmentTransitionError,
    InvalidTeamMessageTransitionError,
)


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


def _assignment() -> TeamAssignment:
    return TeamAssignment.create(
        assignment_id="assignment-001",
        team_id="team-001",
        assigned_by_member_id="lead-001",
        assignee_member_id="member-001",
        prompt="检查数据库迁移。",
        project_task_id="task-001",
        created_at=TIMESTAMP,
    )


def _message() -> TeamMessage:
    return TeamMessage.create(
        message_id="message-001",
        team_id="team-001",
        sender_member_id="lead-001",
        recipient_member_id="member-001",
        sequence=1,
        message_type=TeamMessageType.ASSIGNMENT,
        content="请检查数据库迁移。",
        idempotency_key="lead-001:toolu-001",
        created_at=TIMESTAMP,
    )


def test_team_and_member_keep_persistent_identity_separate_from_runtime_activity() -> None:
    team = Team.create(
        team_id="team-001",
        workspace_id="workspace-001",
        lead_member_id="lead-001",
        created_at=TIMESTAMP,
    )
    member = TeamMember.create(
        member_id="member-001",
        team_id=team.team_id,
        name="alice",
        role="后端开发",
        session_id="session-alice",
        created_at=TIMESTAMP,
    )

    assert team.lead_member_id == "lead-001"
    assert member.session_id == "session-alice"
    with pytest.raises(FrozenInstanceError):
        member.role = "测试"  # type: ignore[misc]


def test_assignment_lifecycle_keeps_project_task_reference_explicit() -> None:
    assignment = _assignment()

    started = assignment.start(run_id="run-001", occurred_at=TIMESTAMP)
    completed = started.complete(occurred_at=TIMESTAMP + timedelta(seconds=1))

    assert assignment.status is TeamAssignmentStatus.PENDING
    assert assignment.project_task_id == "task-001"
    assert started.status is TeamAssignmentStatus.IN_PROGRESS
    assert started.attempt == 1
    assert started.last_run_id == "run-001"
    assert completed.status is TeamAssignmentStatus.COMPLETED
    assert completed.project_task_id == "task-001"


def test_assignment_recovers_interrupted_run_without_faking_completion() -> None:
    started = _assignment().start(run_id="run-001", occurred_at=TIMESTAMP)

    recovered = started.mark_recovery_pending(
        reason="进程在 Run 完成前退出。",
        occurred_at=TIMESTAMP + timedelta(seconds=1),
    )

    assert recovered.status is TeamAssignmentStatus.RECOVERY_PENDING
    assert recovered.last_run_id == "run-001"
    assert recovered.failure_reason == "进程在 Run 完成前退出。"
    assert recovered.start(
        run_id="run-002",
        occurred_at=TIMESTAMP + timedelta(seconds=2),
    ).attempt == 2


def test_assignment_rejects_invalid_lifecycle_transition() -> None:
    with pytest.raises(InvalidTeamAssignmentTransitionError, match="不能迁移"):
        _assignment().complete(occurred_at=TIMESTAMP)


def test_message_reserve_release_and_consume_preserve_identity_and_order() -> None:
    message = _message()

    reserved = message.reserve(reservation_id="reservation-001", occurred_at=TIMESTAMP)
    released = reserved.release()
    consumed = released.reserve(
        reservation_id="reservation-002",
        occurred_at=TIMESTAMP,
    ).consume(
        reservation_id="reservation-002",
        session_id="session-alice",
        run_id="run-001",
        occurred_at=TIMESTAMP + timedelta(seconds=1),
    )

    assert message.delivery_status is TeamMessageDeliveryStatus.UNREAD
    assert reserved.delivery_status is TeamMessageDeliveryStatus.RESERVED
    assert released.delivery_status is TeamMessageDeliveryStatus.UNREAD
    assert consumed.delivery_status is TeamMessageDeliveryStatus.CONSUMED
    assert consumed.consumed_by_session_id == "session-alice"
    assert consumed.consumed_by_run_id == "run-001"
    assert consumed.sequence == 1


def test_message_rejects_wrong_reservation_or_invalid_sender_receiver_pair() -> None:
    reserved = _message().reserve(reservation_id="reservation-001", occurred_at=TIMESTAMP)

    with pytest.raises(InvalidTeamMessageTransitionError, match="确认其他预留"):
        reserved.consume(
            reservation_id="reservation-002",
            session_id="session-alice",
            run_id="run-001",
            occurred_at=TIMESTAMP,
        )
    with pytest.raises(ValueError, match="不能是同一成员"):
        TeamMessage.create(
            team_id="team-001",
            sender_member_id="member-001",
            recipient_member_id="member-001",
            sequence=1,
            message_type=TeamMessageType.PLAIN,
            content="自发消息。",
            idempotency_key="member-001:toolu-001",
            created_at=TIMESTAMP,
        )


def test_inbox_reservation_requires_one_recipient_and_sorted_sequences() -> None:
    first = _message().reserve(reservation_id="reservation-001", occurred_at=TIMESTAMP)
    second = TeamMessage.create(
        message_id="message-002",
        team_id="team-001",
        sender_member_id="lead-001",
        recipient_member_id="member-001",
        sequence=2,
        message_type=TeamMessageType.PLAIN,
        content="补充信息。",
        idempotency_key="lead-001:toolu-002",
        created_at=TIMESTAMP,
    ).reserve(reservation_id="reservation-001", occurred_at=TIMESTAMP)

    reservation = InboxReservation(
        team_id="team-001",
        recipient_member_id="member-001",
        reservation_id="reservation-001",
        messages=(first, second),
        reserved_at=TIMESTAMP,
    )

    assert tuple(message.message_id for message in reservation.messages) == (
        "message-001",
        "message-002",
    )
    with pytest.raises(ValueError, match="升序排列"):
        InboxReservation(
            team_id="team-001",
            recipient_member_id="member-001",
            reservation_id="reservation-001",
            messages=(second, first),
            reserved_at=TIMESTAMP,
        )


def test_prompt_execution_requires_runtime_links_but_not_model_specific_types() -> None:
    execution = TeamPromptExecution(
        session_id="session-alice",
        run_id="run-001",
        response_text="迁移检查完成。",
    )

    assert execution.response_text == "迁移检查完成。"
    with pytest.raises(ValueError, match="response_text"):
        TeamPromptExecution(
            session_id="session-alice",
            run_id="run-001",
            response_text=object(),  # type: ignore[arg-type]
        )
