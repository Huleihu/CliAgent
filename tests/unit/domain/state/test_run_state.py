from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from local_dev_agent.domain.state.errors import InvalidRunTransitionError
from local_dev_agent.domain.state.run import RunState, RunStatus


def test_run_follows_the_happy_path() -> None:
    started_at = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    run = RunState.create(
        session_id="session-1",
        run_id="run-1",
        created_at=started_at,
    )

    recovering = run.transition_to(RunStatus.RECOVERING, occurred_at=started_at)
    running = recovering.transition_to(RunStatus.RUNNING, occurred_at=started_at)
    completed = running.transition_to(RunStatus.COMPLETED, occurred_at=started_at)

    assert run.status is RunStatus.QUEUED
    assert completed.status is RunStatus.COMPLETED
    assert completed.is_terminal is True
    assert completed.state_version == 4
    assert [item.target_status for item in completed.transition_history] == [
        RunStatus.RECOVERING,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]


def test_run_recovers_after_waiting_for_approval() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    run = RunState.create(session_id="session-1", created_at=timestamp)

    waiting = (
        run.transition_to(RunStatus.RECOVERING, occurred_at=timestamp)
        .transition_to(RunStatus.RUNNING, occurred_at=timestamp)
        .transition_to(RunStatus.WAITING_APPROVAL, occurred_at=timestamp)
    )
    resumed = (
        waiting.transition_to(RunStatus.RECOVERING, occurred_at=timestamp)
        .transition_to(RunStatus.RUNNING, occurred_at=timestamp)
    )

    assert waiting.status is RunStatus.WAITING_APPROVAL
    assert resumed.status is RunStatus.RUNNING


def test_run_rejects_an_invalid_transition() -> None:
    run = RunState.create(session_id="session-1")

    with pytest.raises(InvalidRunTransitionError, match="queued.*completed"):
        run.transition_to(RunStatus.COMPLETED)

    assert run.status is RunStatus.QUEUED


def test_terminal_run_cannot_restart() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    completed = (
        RunState.create(session_id="session-1", created_at=timestamp)
        .transition_to(RunStatus.RECOVERING, occurred_at=timestamp)
        .transition_to(RunStatus.RUNNING, occurred_at=timestamp)
        .transition_to(RunStatus.COMPLETED, occurred_at=timestamp)
    )

    with pytest.raises(InvalidRunTransitionError, match="completed.*running"):
        completed.transition_to(RunStatus.RUNNING)


def test_run_state_cannot_be_mutated_directly() -> None:
    run = RunState.create(session_id="session-1")

    with pytest.raises(FrozenInstanceError):
        run.status = RunStatus.RUNNING  # type: ignore[misc]


def test_run_rejects_a_naive_timestamp_with_a_chinese_message() -> None:
    naive_timestamp = datetime(2026, 7, 23, 9, 0)

    with pytest.raises(ValueError, match="运行时间戳必须包含时区信息"):
        RunState.create(session_id="session-1", created_at=naive_timestamp)
