from pathlib import Path

import pytest

from local_dev_agent.worktrees import WorktreeRunDirectoryUnavailableError
from local_dev_agent.worktrees.adapters import FilesystemWorktreeRunDirectoryResolver


def test_resolver_uses_main_workspace_for_unbound_task_and_worktree_for_bound_task(
    tmp_path: Path,
) -> None:
    main_workspace = tmp_path / "project"
    worktrees_directory = main_workspace / ".worktrees"
    api_login = worktrees_directory / "api-login"
    api_login.mkdir(parents=True)
    resolver = FilesystemWorktreeRunDirectoryResolver(
        main_workspace=main_workspace,
        worktrees_directory=worktrees_directory,
    )

    assert resolver.resolve(worktree_name=None) == main_workspace.resolve()
    assert resolver.resolve(worktree_name="api-login") == api_login.resolve()


def test_resolver_rejects_missing_bound_worktree_instead_of_falling_back(tmp_path: Path) -> None:
    main_workspace = tmp_path / "project"
    main_workspace.mkdir()
    resolver = FilesystemWorktreeRunDirectoryResolver(
        main_workspace=main_workspace,
        worktrees_directory=main_workspace / ".worktrees",
    )

    with pytest.raises(WorktreeRunDirectoryUnavailableError, match="api-login"):
        resolver.resolve(worktree_name="api-login")
