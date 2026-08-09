"""S18 工作树隔离的领域契约与应用服务。"""

from .errors import (
    GitWorktreeLifecycleError,
    InvalidWorktreeNameError,
    WorktreeError,
    WorktreeEventJournalError,
    WorktreeOperationConflictError,
    WorktreeRunDirectoryUnavailableError,
    WorktreeUnsafeToRemoveError,
)
from .ports import (
    WorktreeApplicationService,
    WorktreeClock,
    WorktreeEventJournal,
    WorktreeLifecycleGateway,
    WorktreeRunDirectoryResolver,
)
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
    "GitWorktreeLifecycleError",
    "Worktree",
    "WorktreeApplicationService",
    "WorktreeChanges",
    "WorktreeClock",
    "WorktreeError",
    "WorktreeEventJournal",
    "WorktreeEventJournalError",
    "WorktreeEventType",
    "WorktreeLifecycleEvent",
    "WorktreeLifecycleGateway",
    "WorktreeOperationConflictError",
    "WorktreeOperationResult",
    "WorktreeRunDirectoryResolver",
    "WorktreeRunDirectoryUnavailableError",
    "WorktreeService",
    "WorktreeUnsafeToRemoveError",
    "validate_worktree_name",
    "worktree_branch_name",
]
