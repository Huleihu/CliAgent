"""受工作区边界限制的 UTF-8 文本写入工具。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool, ToolWorkingDirectoryResolver
from ..schema import ToolDefinition, ToolExecutionContext
from ..workspace import WorkspaceBoundary


class WriteFileTool(Tool):
    """创建或覆盖工作区内的 UTF-8 文本文件。"""

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
            name="write_file",
            description="创建或覆盖工作区内的 UTF-8 文本文件，仅接受相对路径。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作区的目标文件路径。",
                    },
                    "content": {
                        "type": "string",
                        "description": "将完整写入目标文件的 UTF-8 文本内容。",
                    },
                },
                "required": ["path", "content"],
            },
            tags=("filesystem", "write"),
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
        """创建父目录后写入文本，并返回规范化路径与 UTF-8 字节数。"""

        path = self._read_path(arguments)
        content = self._read_content(arguments)
        workspace = self._resolve_workspace(context)
        target_file = workspace.resolve_write_file(path)
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(content.encode("utf-8"))
        except OSError as error:
            raise ToolExecutionError(f"无法写入文件：{path}。") from error

        return {
            "path": target_file.relative_to(workspace.root).as_posix(),
            "bytes_written": len(content.encode("utf-8")),
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
    def _read_content(arguments: Mapping[str, object]) -> str:
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolValidationError("字段“content”必须是字符串。")
        return content
