import pytest

from local_dev_agent.recovery import OutputBudgetUpgradePolicy


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
