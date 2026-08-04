from datetime import datetime

import pytest

from local_dev_agent.worktrees import (
    InvalidWorktreeNameError,
    Worktree,
    WorktreeChanges,
    WorktreeEventType,
    WorktreeLifecycleEvent,
    validate_worktree_name,
    worktree_branch_name,
)


@pytest.mark.parametrize("name", ("test1", "api-login", "A.b_c-2"))
def test_validate_worktree_name_accepts_a_single_safe_path_segment(name: str) -> None:
    assert validate_worktree_name(name) == name
    assert worktree_branch_name(name) == f"wt/{name}"


@pytest.mark.parametrize(
    "name",
    ("", ".", "..", "../test", "nested/test", "nested\\test", "空 格", "a" * 65),
)
def test_validate_worktree_name_rejects_empty_traversal_and_illegal_names(
    name: str,
) -> None:
    with pytest.raises(InvalidWorktreeNameError, match="工作树名称"):
        validate_worktree_name(name)


def test_worktree_changes_are_clean_only_without_any_local_or_unpushed_work() -> None:
    assert WorktreeChanges(0, 0).is_clean is True
    assert WorktreeChanges(1, 0).is_clean is False
    assert WorktreeChanges(0, 1).is_clean is False


def test_lifecycle_event_captures_a_successful_create_fact() -> None:
    event = WorktreeLifecycleEvent(
        event_type=WorktreeEventType.CREATE,
        operation_id="call-create-1",
        worktree=Worktree(
            name="api-login",
            directory=".worktrees/api-login",
            branch="wt/api-login",
        ),
        task_id="task-api",
        occurred_at=datetime(2026, 8, 4, 12, 0, 0),
    )

    assert event.worktree.branch == "wt/api-login"
    assert event.task_id == "task-api"
