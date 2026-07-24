"""受工作区边界限制的只读文件列表工具。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition
from ..workspace import WorkspaceBoundary


class ListFilesTool(Tool):
    """列出工作区内匹配模式的文件，不读取、写入或执行任何内容。"""

    _DEFAULT_LIMIT = 200
    _MAX_LIMIT = 1_000

    def __init__(self, workspace: Path) -> None:
        self._workspace = WorkspaceBoundary(workspace)
        self._definition = ToolDefinition(
            name="list_files",
            description="列出工作区内符合 glob 模式的文件，仅返回相对路径。",
            parameters={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "相对于工作区的目录，默认当前工作区。",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "glob 匹配模式，默认 *。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回的文件数量，默认 200，最大 1000。",
                    },
                },
            },
            tags=("filesystem", "read_only"),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回模型可见的静态工具定义。"""

        return self._definition

    def run(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        """返回稳定排序的工作区相对文件路径，并报告是否被截断。"""

        directory = self._read_text(arguments, "directory", default=".")
        pattern = self._read_text(arguments, "pattern", default="*")
        limit = self._read_limit(arguments)
        target_directory = self._workspace.resolve_directory(directory)
        safe_pattern = self._workspace.validate_pattern(pattern)

        try:
            matched_paths = sorted(target_directory.glob(safe_pattern))
        except (OSError, ValueError) as error:
            raise ToolExecutionError(f"文件匹配模式无效：{pattern}。") from error

        files = [
            path.relative_to(self._workspace.root).as_posix()
            for path in matched_paths
            if path.is_file() and self._workspace.contains(path)
        ]
        return {
            "files": files[:limit],
            "truncated": len(files) > limit,
        }

    @staticmethod
    def _read_text(arguments: Mapping[str, object], field_name: str, *, default: str) -> str:
        value = arguments.get(field_name, default)
        if not isinstance(value, str) or not value.strip():
            raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")
        return value

    def _read_limit(self, arguments: Mapping[str, object]) -> int:
        value = arguments.get("limit", self._DEFAULT_LIMIT)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError("字段“limit”必须是整数。")
        if not 1 <= value <= self._MAX_LIMIT:
            raise ToolValidationError(
                f"字段“limit”必须在 1 到 {self._MAX_LIMIT} 之间。"
            )
        return value
