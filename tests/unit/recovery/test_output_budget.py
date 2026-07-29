import pytest

from local_dev_agent.recovery import (
    OutputBudgetUpgradePolicy,
    OutputContinuationPolicy,
)


def test_output_budget_upgrade_policy_enables_only_a_higher_budget() -> None:
    policy = OutputBudgetUpgradePolicy(initial_max_output_tokens=8_000)

    assert policy.escalated_max_output_tokens == 64_000
    assert policy.can_upgrade
    assert not OutputBudgetUpgradePolicy(
        initial_max_output_tokens=64_000
    ).can_upgrade


@pytest.mark.parametrize("value", [0, -1, True, "8000"])
def test_output_budget_upgrade_policy_rejects_invalid_budgets(value: object) -> None:
    with pytest.raises(ValueError, match="initial_max_output_tokens"):
        OutputBudgetUpgradePolicy(initial_max_output_tokens=value)  # type: ignore[arg-type]


def test_output_continuation_policy_defaults_to_three_attempts() -> None:
    policy = OutputContinuationPolicy()

    assert policy.max_continuations == 3
    assert "继续" in policy.prompt


@pytest.mark.parametrize("max_continuations", [0, -1, True])
def test_output_continuation_policy_rejects_invalid_attempt_limits(
    max_continuations: object,
) -> None:
    with pytest.raises(ValueError, match="max_continuations"):
        OutputContinuationPolicy(max_continuations=max_continuations)  # type: ignore[arg-type]
