import pytest

from local_dev_agent.todos import TODO_REMINDER_MESSAGE, TodoReminderPolicy


def test_reminder_is_emitted_once_after_the_configured_number_of_tool_turns() -> None:
    policy = TodoReminderPolicy(max_tool_turns_without_update=3)

    policy.record_tool_turn(todo_updated=False)
    policy.record_tool_turn(todo_updated=False)
    assert policy.consume_reminder() is None

    policy.record_tool_turn(todo_updated=False)

    assert policy.consume_reminder() == TODO_REMINDER_MESSAGE
    assert policy.tool_turns_without_update == 0
    assert policy.consume_reminder() is None


def test_successful_todo_update_resets_the_reminder_counter() -> None:
    policy = TodoReminderPolicy(max_tool_turns_without_update=3)
    policy.record_tool_turn(todo_updated=False)
    policy.record_tool_turn(todo_updated=False)

    policy.record_tool_turn(todo_updated=True)
    policy.record_tool_turn(todo_updated=False)
    policy.record_tool_turn(todo_updated=False)

    assert policy.consume_reminder() is None


def test_reminder_rejects_a_non_positive_threshold() -> None:
    with pytest.raises(ValueError, match="待办提醒阈值必须大于或等于 1"):
        TodoReminderPolicy(max_tool_turns_without_update=0)
