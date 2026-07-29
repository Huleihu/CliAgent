import pytest

from local_dev_agent.models import (
    ModelConnectionError,
    ModelOverloadedError,
    ModelResponse,
)
from local_dev_agent.recovery import (
    TransientModelRecoveryExecutor,
    TransientRecoveryExhaustedError,
    TransientRecoveryPolicy,
    TransientRecoveryState,
)


class RecordingSleeper:
    """记录等待时长，避免单元测试依赖真实时间。"""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, delay_seconds: float) -> None:
        self.delays.append(delay_seconds)


class FixedJitterSource:
    """返回固定抖动分数，使退避断言稳定。"""

    def __init__(self, fraction: float) -> None:
        self._fraction = fraction

    def next_fraction(self) -> float:
        return self._fraction


def test_executor_retries_the_same_operation_after_a_transient_error() -> None:
    sleeper = RecordingSleeper()
    executor = TransientModelRecoveryExecutor(
        TransientRecoveryPolicy(),
        primary_model_id="primary-model",
        sleeper=sleeper,
        jitter_source=FixedJitterSource(0),
    )
    attempts: list[str] = []
    outcomes = [ModelConnectionError("连接失败。"), ModelResponse.text_completion("完成。")]

    def operation(model_id: str) -> ModelResponse:
        attempts.append(model_id)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    result = executor.execute(operation, executor.initial_state())

    assert attempts == ["primary-model", "primary-model"]
    assert sleeper.delays == [0.5]
    assert result.response.text == "完成。"
    assert result.state == TransientRecoveryState(current_model_id="primary-model")


def test_executor_switches_the_operation_to_fallback_after_overloads() -> None:
    sleeper = RecordingSleeper()
    executor = TransientModelRecoveryExecutor(
        TransientRecoveryPolicy(fallback_model_id="fallback-model"),
        primary_model_id="primary-model",
        sleeper=sleeper,
        jitter_source=FixedJitterSource(0),
    )
    attempts: list[str] = []
    outcomes = [
        ModelOverloadedError("服务过载。"),
        ModelOverloadedError("服务过载。"),
        ModelOverloadedError("服务过载。"),
        ModelResponse.text_completion("完成。"),
    ]

    def operation(model_id: str) -> ModelResponse:
        attempts.append(model_id)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    result = executor.execute(operation, executor.initial_state())

    assert attempts == [
        "primary-model",
        "primary-model",
        "primary-model",
        "fallback-model",
    ]
    assert sleeper.delays == [0.5, 1.0, 2.0]
    assert result.state == TransientRecoveryState(current_model_id="fallback-model")


def test_executor_raises_after_the_configured_retry_budget_is_exhausted() -> None:
    sleeper = RecordingSleeper()
    error = ModelConnectionError("连接失败。")
    executor = TransientModelRecoveryExecutor(
        TransientRecoveryPolicy(max_retries=1),
        primary_model_id="primary-model",
        sleeper=sleeper,
        jitter_source=FixedJitterSource(0),
    )
    attempts: list[str] = []

    def operation(model_id: str) -> ModelResponse:
        attempts.append(model_id)
        raise error

    with pytest.raises(TransientRecoveryExhaustedError) as error_info:
        executor.execute(operation, executor.initial_state())

    assert attempts == ["primary-model", "primary-model"]
    assert sleeper.delays == [0.5]
    assert error_info.value.__cause__ is error
