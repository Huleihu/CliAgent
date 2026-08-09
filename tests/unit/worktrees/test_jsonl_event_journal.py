import json
from datetime import datetime, timezone

import pytest

from local_dev_agent.worktrees import (
    Worktree,
    WorktreeEventJournalError,
    WorktreeEventType,
    WorktreeLifecycleEvent,
)
from local_dev_agent.worktrees.adapters import JsonlWorktreeEventJournal


def _event(operation_id: str = "call-create-1") -> WorktreeLifecycleEvent:
    return WorktreeLifecycleEvent(
        event_type=WorktreeEventType.CREATE,
        operation_id=operation_id,
        worktree=Worktree(
            name="api-login",
            directory=".worktrees/api-login",
            branch="wt/api-login",
            base_commit="abc123",
        ),
        task_id="task-api",
        occurred_at=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )


def test_jsonl_journal_appends_and_recovers_a_versioned_lifecycle_event(tmp_path) -> None:
    path = tmp_path / ".worktrees" / "events.jsonl"
    journal = JsonlWorktreeEventJournal(path)

    journal.append(_event())

    recovered = JsonlWorktreeEventJournal(path).find_by_operation_id("call-create-1")

    assert recovered == _event()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["state"]["worktree"]["base_commit"] == "abc123"


def test_jsonl_journal_rejects_duplicate_operation_ids_without_overwriting_history(tmp_path) -> None:
    journal = JsonlWorktreeEventJournal(tmp_path / "events.jsonl")
    journal.append(_event())

    with pytest.raises(WorktreeEventJournalError, match="不能重复追加"):
        journal.append(_event())

    assert journal.find_by_operation_id("call-create-1") == _event()


def test_jsonl_journal_rejects_a_corrupted_history_line(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{\n", encoding="utf-8")

    with pytest.raises(WorktreeEventJournalError, match="第 1 行"):
        JsonlWorktreeEventJournal(path).find_by_operation_id("call-create-1")
