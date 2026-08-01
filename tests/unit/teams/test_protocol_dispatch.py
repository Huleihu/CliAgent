from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from local_dev_agent.teams import (
    JsonFileTeamInboxRepository,
    JsonFileTeamProtocolStateRepository,
    TeamMessage,
    TeamMessageType,
    TeamProtocolCoordinator,
    TeamProtocolDecision,
    TeamProtocolDispatchDisposition,
    TeamProtocolState,
    TeamProtocolStatus,
    TeamProtocolType,
)
from local_dev_agent.teams.errors import TeamProtocolRequestConflictError


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class AdvancingClock:
    """为协议消息提供严格递增的时间，便于断言持久化后的终态。"""

    def __init__(self) -> None:
        self._current = TIMESTAMP

    def now(self) -> datetime:
        result = self._current
        self._current += timedelta(seconds=1)
        return result


def _coordinator(tmp_path: Path) -> tuple[TeamProtocolCoordinator, JsonFileTeamInboxRepository]:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    return (
        TeamProtocolCoordinator(
            state_repository=JsonFileTeamProtocolStateRepository(tmp_path),
            inbox_repository=inbox,
            clock=AdvancingClock(),
        ),
        inbox,
    )


def _state(protocol_type: TeamProtocolType) -> TeamProtocolState:
    if protocol_type is TeamProtocolType.SHUTDOWN:
        sender_member_id, target_member_id = "lead-001", "member-001"
    else:
        sender_member_id, target_member_id = "member-001", "lead-001"
    return TeamProtocolState.create(
        request_id=f"request-{protocol_type.value}",
        team_id="team-001",
        protocol_type=protocol_type,
        sender_member_id=sender_member_id,
        target_member_id=target_member_id,
        payload="请确认本次 Team 协议请求。",
        created_at=TIMESTAMP,
    )


def test_open_request_persists_and_delivers_idempotently(tmp_path: Path) -> None:
    coordinator, inbox = _coordinator(tmp_path)
    state = _state(TeamProtocolType.PLAN_APPROVAL)

    persisted, request = coordinator.open_request(
        state=state,
        message_id="request-message-001",
        idempotency_key="protocol:request-plan-approval",
    )
    replayed_state, replayed_request = coordinator.open_request(
        state=state,
        message_id="request-message-001",
        idempotency_key="protocol:request-plan-approval",
    )

    assert persisted == state
    assert replayed_state == state
    assert replayed_request == request
    assert inbox.list_unread(team_id="team-001", recipient_member_id="lead-001") == (
        request,
    )

    conflicting_state = TeamProtocolState.create(
        request_id=state.request_id,
        team_id=state.team_id,
        protocol_type=state.protocol_type,
        sender_member_id=state.sender_member_id,
        target_member_id=state.target_member_id,
        payload="这是另一项不同的审批请求。",
        created_at=TIMESTAMP,
    )
    with pytest.raises(TeamProtocolRequestConflictError):
        coordinator.open_request(
            state=conflicting_state,
            message_id="request-message-conflict",
            idempotency_key="protocol:request-conflict",
        )


def test_shutdown_request_auto_responds_then_response_resolves_state(tmp_path: Path) -> None:
    coordinator, inbox = _coordinator(tmp_path)
    state = _state(TeamProtocolType.SHUTDOWN)
    coordinator.open_request(
        state=state,
        message_id="shutdown-request-001",
        idempotency_key="protocol:shutdown-request-001",
    )
    request = inbox.list_unread(team_id="team-001", recipient_member_id="member-001")[0]

    request_result = coordinator.dispatch(request)

    assert request_result.disposition is TeamProtocolDispatchDisposition.STOP_MEMBER
    assert request_result.state == state
    assert len(request_result.emitted_messages) == 1
    response = request_result.emitted_messages[0]
    assert response.message_type is TeamMessageType.SHUTDOWN_RESPONSE
    assert response.protocol_decision is TeamProtocolDecision.APPROVED

    response_result = coordinator.dispatch(response)

    assert response_result.disposition is TeamProtocolDispatchDisposition.HANDLED
    assert response_result.state is not None
    assert response_result.state.status is TeamProtocolStatus.APPROVED
    assert (
        JsonFileTeamProtocolStateRepository(tmp_path).get(state.request_id)
        == response_result.state
    )


def test_plan_approval_requires_matching_response_but_forwards_agent_messages(
    tmp_path: Path,
) -> None:
    coordinator, inbox = _coordinator(tmp_path)
    state = _state(TeamProtocolType.PLAN_APPROVAL)
    coordinator.open_request(
        state=state,
        message_id="plan-request-001",
        idempotency_key="protocol:plan-request-001",
    )
    request = inbox.list_unread(team_id="team-001", recipient_member_id="lead-001")[0]

    request_result = coordinator.dispatch(request)
    response = coordinator.send_response(
        request_id=state.request_id,
        sender_member_id="lead-001",
        decision=TeamProtocolDecision.APPROVED,
        content="计划已批准，请继续执行。",
        message_id="plan-response-001",
        idempotency_key="protocol:plan-response-001",
    )
    response_result = coordinator.dispatch(response)

    assert request_result.disposition is TeamProtocolDispatchDisposition.FORWARD_TO_AGENT
    assert request_result.should_forward_to_agent is True
    assert response_result.disposition is TeamProtocolDispatchDisposition.FORWARD_TO_AGENT
    assert response_result.should_forward_to_agent is True
    assert response_result.state is not None
    assert response_result.state.status is TeamProtocolStatus.APPROVED


def test_dispatch_rejects_unknown_or_mismatched_responses_without_state_change(
    tmp_path: Path,
) -> None:
    coordinator, _ = _coordinator(tmp_path)
    state = _state(TeamProtocolType.SHUTDOWN)
    coordinator.open_request(
        state=state,
        message_id="shutdown-request-001",
        idempotency_key="protocol:shutdown-request-001",
    )
    unknown_response = TeamMessage.create(
        message_id="unknown-response-001",
        team_id="team-001",
        sender_member_id="member-001",
        recipient_member_id="lead-001",
        sequence=1,
        message_type=TeamMessageType.SHUTDOWN_RESPONSE,
        content="已停止。",
        idempotency_key="protocol:unknown-response-001",
        request_id="request-missing",
        protocol_decision=TeamProtocolDecision.APPROVED,
        created_at=TIMESTAMP,
    )
    mismatched_response = TeamMessage.create(
        message_id="mismatched-response-001",
        team_id="team-001",
        sender_member_id="member-001",
        recipient_member_id="lead-001",
        sequence=2,
        message_type=TeamMessageType.PLAN_APPROVAL_RESPONSE,
        content="错误地使用了审批响应类型。",
        idempotency_key="protocol:mismatched-response-001",
        request_id=state.request_id,
        protocol_decision=TeamProtocolDecision.APPROVED,
        created_at=TIMESTAMP,
    )

    unknown_result = coordinator.dispatch(unknown_response)
    mismatch_result = coordinator.dispatch(mismatched_response)

    assert unknown_result.disposition is TeamProtocolDispatchDisposition.FAILED
    assert unknown_result.failure_reason is not None
    assert "不存在" in unknown_result.failure_reason
    assert mismatch_result.disposition is TeamProtocolDispatchDisposition.FAILED
    assert mismatch_result.failure_reason is not None
    assert "消息类型" in mismatch_result.failure_reason
    persisted = JsonFileTeamProtocolStateRepository(tmp_path).get(state.request_id)
    assert persisted is not None
    assert persisted.status is TeamProtocolStatus.PENDING
