"""S18 工作树隔离的领域契约与应用服务。"""

from .errors import (
    InvalidWorktreeNameError,
    WorktreeError,
    WorktreeOperationConflictError,
    WorktreeUnsafeToRemoveError,
)
from .ports import WorktreeClock, WorktreeEventJournal, WorktreeLifecycleGateway
from .schema import (
    Worktree,
    WorktreeChanges,
    WorktreeEventType,
    WorktreeLifecycleEvent,
    WorktreeOperationResult,
    validate_worktree_name,
    worktree_branch_name,
)
from .service import WorktreeService

__all__ = [
    "InvalidWorktreeNameError",
    "Worktree",
    "WorktreeChanges",
    "WorktreeClock",
    "WorktreeError",
    "WorktreeEventJournal",
    "WorktreeEventType",
    "WorktreeLifecycleEvent",
    "WorktreeLifecycleGateway",
    "WorktreeOperationConflictError",
    "WorktreeOperationResult",
    "WorktreeService",
    "WorktreeUnsafeToRemoveError",
    "validate_worktree_name",
    "worktree_branch_name",
]
