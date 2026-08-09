"""将受控工作树名称解析为成员 Run 目录的文件系统适配器。"""

from __future__ import annotations

from pathlib import Path

from ..errors import WorktreeRunDirectoryUnavailableError
from ..schema import validate_worktree_name


class FilesystemWorktreeRunDirectoryResolver:
    """只允许从固定工作树目录选择已存在的工作树，不会改变进程 cwd。"""

    def __init__(self, *, main_workspace: Path, worktrees_directory: Path) -> None:
        if not isinstance(main_workspace, Path):
            raise TypeError("主工作区必须是 Path 对象。")
        if not isinstance(worktrees_directory, Path):
            raise TypeError("工作树父目录必须是 Path 对象。")
        self._main_workspace = self._require_directory(main_workspace, subject="主工作区")
        self._worktrees_directory = worktrees_directory.resolve()
        try:
            self._worktrees_directory.relative_to(self._main_workspace)
        except ValueError as error:
            raise ValueError("工作树父目录必须位于主工作区内。") from error

    def resolve(self, *, worktree_name: str | None) -> Path:
        """未绑定时返回主工作区；绑定目录缺失、越界时显式失败。"""

        if worktree_name is None:
            return self._main_workspace
        name = validate_worktree_name(worktree_name)
        directory = (self._worktrees_directory / name).resolve()
        try:
            directory.relative_to(self._worktrees_directory)
        except ValueError as error:
            raise WorktreeRunDirectoryUnavailableError(
                name=name,
                detail="解析后的目录越出受控工作树父目录",
            ) from error
        if not directory.is_dir():
            raise WorktreeRunDirectoryUnavailableError(name=name, detail="目录不存在或不是目录")
        return directory

    @staticmethod
    def _require_directory(directory: Path, *, subject: str) -> Path:
        resolved_directory = directory.resolve()
        if not resolved_directory.is_dir():
            raise ValueError(f"{subject}不存在或不是目录：{resolved_directory}。")
        return resolved_directory
