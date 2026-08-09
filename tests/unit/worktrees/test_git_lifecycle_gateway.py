from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_dev_agent.worktrees import GitWorktreeLifecycleError
from local_dev_agent.worktrees.adapters import GitWorktreeLifecycleGateway


def _git(root: Path, *arguments: str) -> str:
    """在临时仓库中执行 Git，测试失败时保留可读的命令输出。"""

    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    """创建拥有初始提交的独立临时 Git 仓库，不接触项目自身仓库。"""

    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "测试用户")
    _git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("初始内容\n", encoding="utf-8")
    (root / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    _git(root, "add", "README.md", ".gitignore")
    _git(root, "commit", "-m", "初始提交")
    return root


def test_gateway_creates_a_managed_worktree_without_changing_process_cwd(tmp_path) -> None:
    root = _repository(tmp_path)
    gateway = GitWorktreeLifecycleGateway(root)
    original_cwd = Path.cwd()

    worktree = gateway.create(name="api-login")

    assert Path.cwd() == original_cwd
    assert Path(worktree.directory).is_dir()
    assert worktree.branch == "wt/api-login"
    assert worktree.base_commit == _git(root, "rev-parse", "HEAD")
    assert _git(Path(worktree.directory), "branch", "--show-current") == "wt/api-login"
    assert gateway.inspect_changes(name="api-login").is_clean is True

    gateway.remove(name="api-login", discard_changes=False)


def test_gateway_detects_uncommitted_and_no_upstream_commits_from_the_creation_base(tmp_path) -> None:
    root = _repository(tmp_path)
    gateway = GitWorktreeLifecycleGateway(root)
    worktree = gateway.create(name="api-login")
    worktree_path = Path(worktree.directory)
    (worktree_path / "login.py").write_text("print('login')\n", encoding="utf-8")

    assert gateway.inspect_changes(name="api-login").uncommitted_file_count == 1

    _git(worktree_path, "add", "login.py")
    _git(worktree_path, "commit", "-m", "实现登录")
    changes = gateway.inspect_changes(name="api-login")

    assert changes.uncommitted_file_count == 0
    assert changes.unpushed_commit_count == 1

    gateway.remove(name="api-login", discard_changes=True)
    assert not worktree_path.exists()


def test_gateway_refuses_to_create_an_existing_managed_worktree_path(tmp_path) -> None:
    root = _repository(tmp_path)
    gateway = GitWorktreeLifecycleGateway(root)
    gateway.create(name="api-login")

    with pytest.raises(GitWorktreeLifecycleError, match="已存在"):
        gateway.create(name="api-login")

    gateway.remove(name="api-login", discard_changes=False)
