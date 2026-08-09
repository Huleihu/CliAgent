"""使用受控 Git 子进程实现工作树生命周期端口。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import GitWorktreeLifecycleError
from ..schema import Worktree, WorktreeChanges, validate_worktree_name, worktree_branch_name


class GitWorktreeLifecycleGateway:
    """所有 Git 子进程固定从主仓库根目录启动，绝不改变进程 cwd。"""

    def __init__(
        self,
        repository_root: Path,
        *,
        worktrees_directory: Path | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        if not isinstance(repository_root, Path):
            raise TypeError("Git 仓库根目录必须是 Path 对象。")
        if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            raise ValueError("Git 命令超时必须是正整数秒。")
        self._repository_root = repository_root.resolve()
        directory = worktrees_directory or self._repository_root / ".worktrees"
        if not isinstance(directory, Path):
            raise TypeError("工作树目录必须是 Path 对象。")
        self._worktrees_directory = directory.resolve()
        try:
            self._worktrees_directory.relative_to(self._repository_root)
        except ValueError as error:
            raise ValueError("工作树目录必须位于 Git 仓库根目录内。") from error
        self._timeout_seconds = timeout_seconds

    def create(self, *, name: str) -> Worktree:
        """从当前 HEAD 创建受控分支和工作树，成功后返回基准提交。"""

        path = self._path_for(name)
        if path.exists():
            raise GitWorktreeLifecycleError(
                operation="创建",
                detail=f"目标目录“{path}”已存在",
            )
        base_commit = self._run(("rev-parse", "HEAD"), operation="读取基准提交")
        self._run(
            ("worktree", "add", "-b", worktree_branch_name(name), str(path), "HEAD"),
            operation="创建",
        )
        return Worktree(
            name=name,
            directory=str(path),
            branch=worktree_branch_name(name),
            base_commit=base_commit,
        )

    def inspect_changes(self, *, name: str) -> WorktreeChanges:
        """读取未提交改动，并按 upstream 或创建基准计算未推送提交。"""

        worktree = self._existing_worktree(name)
        status = self._run(
            ("-C", worktree.directory, "status", "--porcelain"),
            operation="检查未提交改动",
        )
        upstream = self._try_run(
            (
                "-C",
                worktree.directory,
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            )
        )
        comparison_base = upstream if upstream is not None else worktree.base_commit
        unpushed = self._run(
            ("-C", worktree.directory, "rev-list", "--count", f"{comparison_base}..HEAD"),
            operation="检查未推送提交",
        )
        try:
            unpushed_count = int(unpushed)
        except ValueError as error:
            raise GitWorktreeLifecycleError(
                operation="检查未推送提交",
                detail="Git 未返回有效的提交计数",
            ) from error
        return WorktreeChanges(
            uncommitted_file_count=len([line for line in status.splitlines() if line]),
            unpushed_commit_count=unpushed_count,
        )

    def remove(self, *, name: str, discard_changes: bool) -> Worktree:
        """移除工作树后删除其受控分支；任一步失败均不伪造成功。"""

        worktree = self._existing_worktree(name)
        command = ["worktree", "remove"]
        if discard_changes:
            command.append("--force")
        command.append(worktree.directory)
        self._run(tuple(command), operation="删除工作树")
        self._run(
            ("branch", "-D" if discard_changes else "-d", worktree.branch),
            operation="删除工作树分支",
        )
        return worktree

    def keep(self, *, name: str) -> Worktree:
        """确认工作树与受控分支仍存在，供人工检查后保留。"""

        return self._existing_worktree(name)

    def _existing_worktree(self, name: str) -> Worktree:
        """从目录、分支和分支 reflog 恢复已有工作树的安全删除基准。"""

        path = self._path_for(name)
        if not path.is_dir():
            raise GitWorktreeLifecycleError(
                operation="读取工作树",
                detail=f"目标目录“{path}”不存在",
            )
        branch = worktree_branch_name(name)
        self._run(("show-ref", "--verify", f"refs/heads/{branch}"), operation="读取工作树分支")
        reflog = self._run(("reflog", "show", "--format=%H", branch), operation="读取工作树基准")
        commits = [commit for commit in reflog.splitlines() if commit]
        if not commits:
            raise GitWorktreeLifecycleError(
                operation="读取工作树基准",
                detail="受控分支缺少可用的创建记录",
            )
        return Worktree(
            name=name,
            directory=str(path),
            branch=branch,
            base_commit=commits[-1],
        )

    def _path_for(self, name: str) -> Path:
        """由严格名称构造并复核受控目录内的唯一直接子目录。"""

        validated_name = validate_worktree_name(name)
        path = self._worktrees_directory / validated_name
        try:
            path.resolve().relative_to(self._worktrees_directory)
        except ValueError as error:
            raise GitWorktreeLifecycleError(
                operation="解析工作树路径",
                detail="目标路径越出了受控工作树目录",
            ) from error
        return path

    def _run(self, arguments: tuple[str, ...], *, operation: str) -> str:
        """运行必须成功的 Git 命令，并把失败收束为中文领域错误。"""

        result = self._execute(arguments, operation=operation)
        if result.returncode != 0:
            raise GitWorktreeLifecycleError(
                operation=operation,
                detail=self._output(result) or "Git 未返回文本输出",
            )
        return self._output(result)

    def _try_run(self, arguments: tuple[str, ...]) -> str | None:
        """探测 upstream；不存在是正常分支状态，其余命令不影响进程 cwd。"""

        result = self._execute(arguments, operation="读取上游分支")
        if result.returncode != 0:
            return None
        return self._output(result)

    def _execute(
        self,
        arguments: tuple[str, ...],
        *,
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        """固定 cwd 启动 git；超时和找不到命令也转换为可诊断错误。"""

        try:
            return subprocess.run(
                ("git", *arguments),
                cwd=self._repository_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as error:
            raise GitWorktreeLifecycleError(operation=operation, detail="找不到 git 命令") from error
        except subprocess.TimeoutExpired as error:
            raise GitWorktreeLifecycleError(operation=operation, detail="命令执行超时") from error
        except OSError as error:
            raise GitWorktreeLifecycleError(operation=operation, detail=str(error)) from error

    @staticmethod
    def _output(result: subprocess.CompletedProcess[str]) -> str:
        """合并并限制外部命令输出，避免异常和日志无限增长。"""

        output = f"{result.stdout}\n{result.stderr}".strip()
        return output[:5000]
