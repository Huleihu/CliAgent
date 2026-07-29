import pytest

from local_dev_agent.models import (
    ModelConnectionError,
    ModelOverloadedError,
    ModelRateLimitError,
    ModelTransientError,
)
from local_dev_agent.recovery import (
    TransientRecoveryPolicy,
    TransientRecoveryState,
)


def test_policy_calculates_capped_exponential_backoff_with_jitter() -> None:
    policy = TransientRecoveryPolicy()
    state = TransientRecoveryState(current_model_id="primary-model")
    error = ModelConnectionError("连接失败。")

    first = policy.decide(error, state, retry_index=0, jitter_fraction=0)
    third = policy.decide(error, state, retry_index=2, jitter_fraction=1)
    capped_delay = policy.decide(error, state, retry_index=6, jitter_fraction=0)
    last_allowed = policy.decide(error, state, retry_index=9, jitter_fraction=0)
    exhausted = policy.decide(error, state, retry_index=10, jitter_fraction=0)

    assert first.should_retry is True
    assert first.delay_seconds == 0.5
    assert third.delay_seconds == 2.5
    assert capped_delay.delay_seconds == 32.0
    assert last_allowed.should_retry is True
    assert exhausted.should_retry is False
    assert exhausted.delay_seconds is None


def test_policy_prioritizes_retry_after_over_exponential_backoff() -> None:
    policy = TransientRecoveryPolicy()
    decision = policy.decide(
        ModelRateLimitError("限流。", retry_after_seconds=7.5),
        TransientRecoveryState(current_model_id="primary-model"),
        retry_index=0,
        jitter_fraction=1,
    )

    assert decision.should_retry is True
    assert decision.delay_seconds == 7.5


def test_policy_switches_to_fallback_after_three_consecutive_overloads() -> None:
    policy = TransientRecoveryPolicy(fallback_model_id="fallback-model")
    error = ModelOverloadedError("服务过载。")
    initial_state = TransientRecoveryState(current_model_id="primary-model")

    first = policy.decide(error, initial_state, retry_index=0, jitter_fraction=0)
    second = policy.decide(error, first.next_state, retry_index=1, jitter_fraction=0)
    third = policy.decide(error, second.next_state, retry_index=2, jitter_fraction=0)

    assert first.next_state.consecutive_overloads == 1
    assert second.next_state.consecutive_overloads == 2
    assert third.fallback_switched is True
    assert third.next_state.current_model_id == "fallback-model"
    assert third.next_state.consecutive_overloads == 0


def test_policy_resets_consecutive_overloads_for_other_failures_and_success() -> None:
    policy = TransientRecoveryPolicy()
    overloaded_state = TransientRecoveryState(
        current_model_id="primary-model",
        consecutive_overloads=2,
    )

    non_overload = policy.decide(
        ModelRateLimitError("限流。"),
        overloaded_state,
        retry_index=0,
        jitter_fraction=0,
    )
    after_success = policy.record_success(
        TransientRecoveryState(
            current_model_id="fallback-model",
            consecutive_overloads=2,
        )
    )

    assert non_overload.next_state.consecutive_overloads == 0
    assert after_success == TransientRecoveryState(current_model_id="fallback-model")


def test_policy_does_not_switch_when_fallback_is_not_configured() -> None:
    policy = TransientRecoveryPolicy()
    decision = policy.decide(
        ModelOverloadedError("服务过载。"),
        TransientRecoveryState(
            current_model_id="primary-model",
            consecutive_overloads=2,
        ),
        retry_index=0,
        jitter_fraction=0,
    )

    assert decision.fallback_switched is False
    assert decision.next_state == TransientRecoveryState(current_model_id="primary-model")


@pytest.mark.parametrize(
    ("policy_arguments", "error_type"),
    [
        ({"max_retries": -1}, ValueError),
        ({"max_delay_seconds": 0.25}, ValueError),
        ({"jitter_ratio": 1.1}, ValueError),
        ({"max_consecutive_overloads": 0}, ValueError),
        ({"fallback_model_id": " "}, ValueError),
    ],
)
def test_policy_rejects_invalid_configuration(policy_arguments, error_type) -> None:
    with pytest.raises(error_type):
        TransientRecoveryPolicy(**policy_arguments)


@pytest.mark.parametrize(
    ("retry_index", "jitter_fraction"),
    [(-1, 0), (0, -0.1), (0, 1.1), (0, float("inf"))],
)
def test_policy_rejects_invalid_decision_inputs(
    retry_index: int,
    jitter_fraction: float,
) -> None:
    with pytest.raises(ValueError):
        TransientRecoveryPolicy().decide(
            ModelTransientError("瞬态错误。"),
            TransientRecoveryState(current_model_id="primary-model"),
            retry_index=retry_index,
            jitter_fraction=jitter_fraction,
        )
