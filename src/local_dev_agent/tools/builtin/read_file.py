"""受工作区边界和输出预算限制的文本文件读取工具。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..errors import ToolValidationError
from ..ports import Tool, ToolWorkingDirectoryResolver
from ..schema import ToolDefinition, ToolExecutionContext
from ..text_files import read_utf8_text
from ..workspace import WorkspaceBoundary


class ReadFileTool(Tool):
    """读取工作区内 UTF-8 文本文件的有限片段，不修改文件。"""

    _DEFAULT_MAX_LINES = 200
    _MAX_MAX_LINES = 1_000
    _MAX_CONTENT_CHARS = 20_000

    def __init__(
        self,
        workspace: Path,
        *,
        working_directory_resolver: ToolWorkingDirectoryResolver | None = None,
    ) -> None:
        self._workspace = WorkspaceBoundary(workspace)
        if working_directory_resolver is not None and not callable(
            getattr(working_directory_resolver, "resolve", None)
        ):
            raise TypeError("工作目录解析器必须提供 resolve 方法。")
        self._working_directory_resolver = working_directory_resolver
        self._definition = ToolDefinition(
            name="read_file",
            description="读取工作区内 UTF-8 文本文件的有限行数，仅返回相对路径和文本内容。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作区的文本文件路径。",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "开始读取的行号，从 1 开始，默认 1。",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "最多读取的行数，默认 200，最大 1000。",
                    },
                },
                "required": ["path"],
            },
            tags=("filesystem", "read_only"),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回模型可见的静态工具定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """读取有限文本片段，避免单次工具结果占满模型上下文。"""

        path = self._read_path(arguments)
        start_line = self._read_positive_integer(arguments, "start_line", default=1)
        max_lines = self._read_positive_integer(
            arguments,
            "max_lines",
            default=self._DEFAULT_MAX_LINES,
            maximum=self._MAX_MAX_LINES,
        )
        workspace = self._resolve_workspace(context)
        target_file = workspace.resolve_file(path)
        text = read_utf8_text(target_file, path)
        lines = text.splitlines()
        selected_lines = lines[start_line - 1 : start_line - 1 + max_lines]
        content = "\n".join(selected_lines)
        content_truncated = len(content) > self._MAX_CONTENT_CHARS
        if content_truncated:
            content = content[: self._MAX_CONTENT_CHARS]
        lines_truncated = len(lines) > start_line - 1 + len(selected_lines)

        return {
            "path": target_file.relative_to(workspace.root).as_posix(),
            "content": content,
            "total_lines": len(lines),
            "truncated": lines_truncated or content_truncated,
        }

    def _resolve_workspace(self, context: ToolExecutionContext | None) -> WorkspaceBoundary:
        """按本次 Run 选择文件边界，未配置隔离时保持原有工作区。"""

        if self._working_directory_resolver is None:
            return self._workspace
        return WorkspaceBoundary(self._working_directory_resolver.resolve(context=context))

    @staticmethod
    def _read_path(arguments: Mapping[str, object]) -> str:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolValidationError("字段“path”必须是非空字符串。")
        return path

    @staticmethod
    def _read_positive_integer(
        arguments: Mapping[str, object],
        field_name: str,
        *,
        default: int,
        maximum: int | None = None,
    ) -> int:
        value = arguments.get(field_name, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError(f"字段“{field_name}”必须是整数。")
        if value < 1:
            raise ToolValidationError(f"字段“{field_name}”必须大于或等于 1。")
        if maximum is not None and value > maximum:
            raise ToolValidationError(f"字段“{field_name}”不能大于 {maximum}。")
        return value
