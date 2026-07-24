"""工作区文件工具共享的路径安全边界。"""

from __future__ import annotations

from pathlib import Path

from .errors import ToolExecutionError, ToolValidationError


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
