from datetime import datetime

from local_dev_agent.worktrees import (
    Worktree,
    WorktreeChanges,
    WorktreeClock,
    WorktreeEventJournal,
    WorktreeLifecycleEvent,
    WorktreeLifecycleGateway,
)


def test_worktree_lifecycle_gateway_port_accepts_a_structural_implementation() -> None:
    worktree = Worktree("test1", ".worktrees/test1", "wt/test1")

    class FakeWorktreeLifecycleGateway:
        def create(self, *, name: str) -> Worktree:
            assert name == "test1"
            return worktree

        def inspect_changes(self, *, name: str) -> WorktreeChanges:
            assert name == "test1"
            return WorktreeChanges(0, 0)

        def remove(self, *, name: str, discard_changes: bool) -> Worktree:
            assert name == "test1"
            assert discard_changes is False
            return worktree

        def keep(self, *, name: str) -> Worktree:
            assert name == "test1"
            return worktree

    gateway: WorktreeLifecycleGateway = FakeWorktreeLifecycleGateway()

    assert gateway.create(name="test1") == worktree
    assert gateway.inspect_changes(name="test1").is_clean is True
    assert gateway.keep(name="test1") == worktree
    assert gateway.remove(name="test1", discard_changes=False) == worktree


def test_event_journal_and_clock_ports_accept_structural_implementations() -> None:
    class FakeEventJournal:
        def find_by_operation_id(self, operation_id: str) -> WorktreeLifecycleEvent | None:
            assert operation_id == "call-1"
            return None

        def append(self, event: WorktreeLifecycleEvent) -> None:
            assert isinstance(event, WorktreeLifecycleEvent)

    class FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 8, 4, 12, 0, 0)

    journal: WorktreeEventJournal = FakeEventJournal()
    clock: WorktreeClock = FixedClock()

    assert journal.find_by_operation_id("call-1") is None
    assert clock.now() == datetime(2026, 8, 4, 12, 0, 0)
