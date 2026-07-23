from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.domain.state.errors import InvalidSessionTransitionError
from local_dev_agent.domain.state.session import SessionState, SessionStatus


def create_session(*, created_at: datetime | None = None) -> SessionState:
    """创建供测试使用、身份边界明确的会话。"""

    return SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=created_at,
    )


def test_session_follows_its_lifecycle() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    session = create_session(created_at=timestamp)

    active = session.transition_to(SessionStatus.ACTIVE, occurred_at=timestamp)
    suspended = active.transition_to(SessionStatus.SUSPENDED, occurred_at=timestamp)
    resumed = suspended.transition_to(SessionStatus.ACTIVE, occurred_at=timestamp)
    archived = resumed.transition_to(SessionStatus.ARCHIVED, occurred_at=timestamp)

    assert session.status is SessionStatus.CREATED
    assert archived.status is SessionStatus.ARCHIVED
    assert archived.is_terminal is True
    assert archived.state_version == 5
    assert [item.target_status for item in archived.transition_history] == [
        SessionStatus.ACTIVE,
        SessionStatus.SUSPENDED,
        SessionStatus.ACTIVE,
        SessionStatus.ARCHIVED,
    ]


def test_session_sequentially_associates_multiple_runs() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    session = create_session(created_at=timestamp)

    first_finished = (
        session.start_run("run-1", occurred_at=timestamp)
        .finish_run("run-1", occurred_at=timestamp)
    )
    second_started = first_finished.start_run("run-2", occurred_at=timestamp)

    assert first_finished.status is SessionStatus.ACTIVE
    assert first_finished.active_run_id is None
    assert second_started.active_run_id == "run-2"
    assert second_started.state_version == 4


def test_session_rejects_a_second_or_mismatched_active_run() -> None:
    session = create_session().start_run("run-1")

    with pytest.raises(ValueError, match="已有活跃运行"):
        session.start_run("run-2")
    with pytest.raises(ValueError, match="当前关联的活跃运行"):
        session.finish_run("run-2")


def test_session_cannot_change_lifecycle_while_a_run_is_active() -> None:
    session = create_session().start_run("run-1")

    with pytest.raises(ValueError, match="存在活跃运行"):
        session.transition_to(SessionStatus.SUSPENDED)


def test_session_rejects_an_invalid_transition() -> None:
    session = create_session()

    with pytest.raises(InvalidSessionTransitionError, match="created.*archived"):
        session.transition_to(SessionStatus.ARCHIVED)


def test_terminal_session_cannot_restart() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    archived = (
        create_session(created_at=timestamp)
        .transition_to(SessionStatus.ACTIVE, occurred_at=timestamp)
        .transition_to(SessionStatus.ARCHIVED, occurred_at=timestamp)
    )

    with pytest.raises(InvalidSessionTransitionError, match="archived.*active"):
        archived.transition_to(SessionStatus.ACTIVE)


def test_session_state_cannot_be_mutated_directly() -> None:
    session = create_session()

    with pytest.raises(FrozenInstanceError):
        session.status = SessionStatus.ACTIVE  # type: ignore[misc]


def test_session_rejects_a_naive_timestamp_with_a_chinese_message() -> None:
    naive_timestamp = datetime(2026, 7, 23, 9, 0)

    with pytest.raises(ValueError, match="会话时间戳必须包含时区信息"):
        create_session(created_at=naive_timestamp)


def test_session_rejects_a_timestamp_earlier_than_its_current_state() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    session = create_session(created_at=timestamp)

    with pytest.raises(ValueError, match="不能早于当前状态的时间"):
        session.transition_to(
            SessionStatus.ACTIVE,
            occurred_at=timestamp - timedelta(seconds=1),
        )
