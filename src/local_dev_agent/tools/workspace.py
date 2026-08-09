"""工作区文件工具共享的路径安全边界。"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from .errors import ToolExecutionError, ToolValidationError

if TYPE_CHECKING:
    from .schema import ToolExecutionContext


class WorkspaceBoundary:
    """将文件工具的可见范围固定在一个已解析的工作区内。"""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise TypeError("工作区根目录必须是 Path 对象。")
        self._root = root.resolve()
        if not self._root.is_dir():
            raise ToolExecutionError(f"工作区目录不存在或不是目录：{self._root}。")

    @property
    def root(self) -> Path:
        """返回不可变的工作区根目录快照。"""

        return self._root

    def resolve_directory(self, directory: str) -> Path:
        """解析工作区内目录，并在访问前拒绝越界路径。"""

        relative_directory = self._validate_relative_path("directory", directory)
        resolved_directory = (self._root / relative_directory).resolve()
        if not self.contains(resolved_directory):
            raise ToolValidationError(f"目录“{directory}”超出工作区边界。")
        if not resolved_directory.is_dir():
            raise ToolExecutionError(f"目录不存在或不是目录：{directory}。")
        return resolved_directory

    def resolve_file(self, path: str) -> Path:
        """解析工作区内文件，并在读取前拒绝越界或非文件目标。"""

        relative_path = self._validate_relative_path("path", path)
        resolved_path = (self._root / relative_path).resolve()
        if not self.contains(resolved_path):
            raise ToolValidationError(f"文件“{path}”超出工作区边界。")
        if not resolved_path.is_file():
            raise ToolExecutionError(f"文件不存在或不是普通文件：{path}。")
        return resolved_path

    def resolve_write_file(self, path: str) -> Path:
        """解析工作区内的可写目标，允许目标文件尚未创建。"""

        relative_path = self._validate_relative_path("path", path)
        resolved_path = (self._root / relative_path).resolve()
        if not self.contains(resolved_path):
            raise ToolValidationError(f"文件“{path}”超出工作区边界。")
        if resolved_path.exists() and not resolved_path.is_file():
            raise ToolExecutionError(f"写入目标不是普通文件：{path}。")
        return resolved_path

    def validate_pattern(self, pattern: str) -> str:
        """拒绝可借由 glob 模式跨越工作区的路径片段。"""

        self._validate_relative_path("pattern", pattern)
        return pattern

    def contains(self, path: Path) -> bool:
        """检查解析后的路径是否仍在工作区内。"""

        try:
            path.resolve().relative_to(self._root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_relative_path(field_name: str, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ToolValidationError(f"字段“{field_name}”不能使用绝对路径或上级目录。")
        return candidate


class InMemoryRunWorkingDirectoryRegistry:
    """为并行 Run 保存独立目录映射，未登记的调用始终回退到主工作区。"""

    def __init__(self, *, main_workspace: Path) -> None:
        self._main_workspace = WorkspaceBoundary(main_workspace).root
        self._directories: dict[str, Path] = {}
        self._lock = RLock()

    def bind(self, *, run_id: str, directory: Path) -> None:
        """登记已创建 Run 的实际目录；同一 Run 不允许悄悄改绑。"""

        normalized_run_id = self._require_run_id(run_id)
        if not isinstance(directory, Path):
            raise TypeError("工作目录必须是 Path 对象。")
        normalized_directory = WorkspaceBoundary(directory).root
        with self._lock:
            existing = self._directories.get(normalized_run_id)
            if existing is not None and existing != normalized_directory:
                raise ValueError(f"Run“{normalized_run_id}”已绑定到其他工作目录。")
            self._directories[normalized_run_id] = normalized_directory

    def release(self, *, run_id: str) -> None:
        """移除一次 Run 的短生命周期映射；重复释放是安全的。"""

        normalized_run_id = self._require_run_id(run_id)
        with self._lock:
            self._directories.pop(normalized_run_id, None)

    def resolve(self, *, context: ToolExecutionContext | None) -> Path:
        """按工具上下文解析目录，主会话和未登记 Run 保持主工作区。"""

        if context is None:
            return self._main_workspace
        with self._lock:
            return self._directories.get(context.run_id, self._main_workspace)

    @staticmethod
    def _require_run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Run 标识必须是非空字符串。")
        return run_id.strip()
