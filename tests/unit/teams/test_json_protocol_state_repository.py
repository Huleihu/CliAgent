from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from local_dev_agent.teams import (
    JsonFileTeamProtocolStateRepository,
    TeamMessage,
    TeamMessageType,
    TeamProtocolDecision,
    TeamProtocolState,
    TeamProtocolType,
)
from local_dev_agent.teams.errors import (
    CorruptedTeamFileError,
    TeamProtocolStateAlreadyExistsError,
)


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


def _state() -> TeamProtocolState:
    return TeamProtocolState.create(
        request_id="request-001",
        team_id="team-001",
        protocol_type=TeamProtocolType.PLAN_APPROVAL,
        sender_member_id="member-001",
        target_member_id="lead-001",
        payload="先拆分认证适配器，再迁移调用方。",
        created_at=TIMESTAMP,
    )


def _response() -> TeamMessage:
    return TeamMessage.create(
        message_id="response-001",
        team_id="team-001",
        sender_member_id="lead-001",
        recipient_member_id="member-001",
        sequence=1,
        message_type=TeamMessageType.PLAN_APPROVAL_RESPONSE,
        content="批准，可以开始。",
        idempotency_key="protocol:response-001",
        request_id="request-001",
        protocol_decision=TeamProtocolDecision.APPROVED,
        created_at=TIMESTAMP + timedelta(seconds=1),
    )


def test_protocol_state_repository_round_trips_pending_and_resolved_states(tmp_path: Path) -> None:
    repository = JsonFileTeamProtocolStateRepository(tmp_path)
    pending = _state()

    assert repository.add(pending) is pending
    assert JsonFileTeamProtocolStateRepository(tmp_path).get(pending.request_id) == pending
    assert repository.list_pending_for_team(pending.team_id) == (pending,)

    resolved = pending.match_response(_response())

    assert repository.replace(resolved) is resolved
    assert JsonFileTeamProtocolStateRepository(tmp_path).get(resolved.request_id) == resolved
    assert repository.list_pending_for_team(resolved.team_id) == ()


def test_protocol_state_repository_rejects_duplicates_and_corrupted_files(tmp_path: Path) -> None:
    repository = JsonFileTeamProtocolStateRepository(tmp_path)
    state = _state()
    repository.add(state)

    with pytest.raises(TeamProtocolStateAlreadyExistsError, match="已存在"):
        repository.add(state)

    path = tmp_path / "team-001" / "protocols" / "request-001.json"
    path.write_text("不是 JSON", encoding="utf-8")

    with pytest.raises(CorruptedTeamFileError, match="已损坏"):
        repository.get(state.request_id)
