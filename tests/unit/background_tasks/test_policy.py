import pytest

from local_dev_agent.background_tasks import BackgroundExecutionPolicy


@pytest.mark.parametrize(
    ("command", "requested", "expected"),
    [
        ("python -m pytest", None, True),
        ("git status", None, False),
        ("python -m pytest", False, False),
        ("git status", True, True),
    ],
)
def test_background_execution_policy_prefers_explicit_request_then_uses_heuristic(
    command: str,
    requested: bool | None,
    expected: bool,
) -> None:
    assert (
        BackgroundExecutionPolicy().should_run_in_background(
            command=command,
            requested=requested,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("command", "requested", "message"),
    [
        (" ", None, "command”必须是非空字符串"),
        ("git status", "yes", "requested”必须是布尔值或 None"),
    ],
)
def test_background_execution_policy_rejects_invalid_input(
    command: object,
    requested: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BackgroundExecutionPolicy().should_run_in_background(
            command=command,  # type: ignore[arg-type]
            requested=requested,  # type: ignore[arg-type]
        )
