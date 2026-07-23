from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from local_dev_agent.domain.state.errors import InvalidStepTransitionError
from local_dev_agent.domain.state.step import StepState, StepStatus, StepType


def test_step_follows_the_happy_path() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    step = StepState.create(
        run_id="run-1",
        step_id="step-1",
        step_type=StepType.MODEL,
        created_at=timestamp,
    )

    executing = step.transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
    succeeded = executing.transition_to(StepStatus.SUCCEEDED, occurred_at=timestamp)

    assert step.status is StepStatus.PENDING
    assert succeeded.status is StepStatus.SUCCEEDED
    assert succeeded.is_terminal is True
    assert succeeded.state_version == 3
    assert [item.target_status for item in succeeded.transition_history] == [
        StepStatus.EXECUTING,
        StepStatus.SUCCEEDED,
    ]


def test_step_resumes_after_waiting() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    step = StepState.create(
        run_id="run-1",
        step_type=StepType.TOOL,
        created_at=timestamp,
    )

    resumed = (
        step.transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
        .transition_to(StepStatus.WAITING, occurred_at=timestamp)
        .transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
    )

    assert resumed.status is StepStatus.EXECUTING
    assert resumed.is_terminal is False


def test_unknown_step_can_be_reconciled_to_a_final_result() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    step = StepState.create(
        run_id="run-1",
        step_type=StepType.TOOL,
        created_at=timestamp,
    )

    reconciled = (
        step.transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
        .transition_to(StepStatus.UNKNOWN, occurred_at=timestamp)
        .transition_to(StepStatus.SUCCEEDED, occurred_at=timestamp)
    )

    assert reconciled.status is StepStatus.SUCCEEDED
    assert reconciled.is_terminal is True


def test_step_rejects_an_invalid_transition() -> None:
    step = StepState.create(run_id="run-1", step_type=StepType.VERIFY)

    with pytest.raises(InvalidStepTransitionError, match="pending.*succeeded"):
        step.transition_to(StepStatus.SUCCEEDED)

    assert step.status is StepStatus.PENDING


def test_terminal_step_cannot_restart() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    succeeded = (
        StepState.create(
            run_id="run-1",
            step_type=StepType.REFLECT,
            created_at=timestamp,
        )
        .transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
        .transition_to(StepStatus.SUCCEEDED, occurred_at=timestamp)
    )

    with pytest.raises(InvalidStepTransitionError, match="succeeded.*executing"):
        succeeded.transition_to(StepStatus.EXECUTING)


def test_step_state_cannot_be_mutated_directly() -> None:
    step = StepState.create(run_id="run-1", step_type=StepType.PLAN)

    with pytest.raises(FrozenInstanceError):
        step.status = StepStatus.EXECUTING  # type: ignore[misc]


def test_step_rejects_a_naive_timestamp_with_a_chinese_message() -> None:
    naive_timestamp = datetime(2026, 7, 23, 9, 0)

    with pytest.raises(ValueError, match="步骤时间戳必须包含时区信息"):
        StepState.create(
            run_id="run-1",
            step_type=StepType.MODEL,
            created_at=naive_timestamp,
        )


def test_step_rejects_a_non_positive_attempt() -> None:
    with pytest.raises(ValueError, match="步骤尝试次数必须大于或等于 1"):
        StepState.create(run_id="run-1", step_type=StepType.TOOL, attempt=0)
