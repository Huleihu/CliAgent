import pytest

from local_dev_agent.models import (
    ModelConnectionError,
    ModelOverloadedError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelTransientError,
)


@pytest.mark.parametrize(
    "error_type",
    [
        ModelConnectionError,
        ModelTimeoutError,
        ModelRateLimitError,
        ModelOverloadedError,
    ],
)
def test_transient_model_errors_share_retry_metadata(error_type) -> None:
    error = error_type("测试瞬态错误。", retry_after_seconds=1.5)

    assert isinstance(error, ModelTransientError)
    assert error.retry_after_seconds == 1.5


def test_timeout_error_is_a_specialized_connection_error() -> None:
    error = ModelTimeoutError("测试超时。")

    assert isinstance(error, ModelConnectionError)
    assert error.retry_after_seconds is None


@pytest.mark.parametrize(
    "retry_after_seconds",
    [True, -1, float("inf"), float("nan"), "1"],
)
def test_transient_model_error_rejects_invalid_retry_after(
    retry_after_seconds,
) -> None:
    with pytest.raises(ValueError, match="retry_after_seconds"):
        ModelTransientError(
            "测试瞬态错误。",
            retry_after_seconds=retry_after_seconds,
        )
