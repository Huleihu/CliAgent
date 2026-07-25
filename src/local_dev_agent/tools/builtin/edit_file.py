"""受工作区边界限制的首次精确文本替换工具。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext
from ..text_files import read_utf8_text
from ..workspace import WorkspaceBoundary


class EditFileTool(Tool):
    """将工作区 UTF-8 文本文件中的首次精确匹配替换为新文本。"""

    def __init__(self, workspace: Path) -> None:
        self._workspace = WorkspaceBoundary(workspace)
        self._definition = ToolDefinition(
            name="edit_file",
            description="将工作区 UTF-8 文本文件中的首次精确匹配替换为新文本。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作区的既有文本文件路径。",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "需要首次精确匹配的非空原始文本。",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "替换后的文本，可为空字符串以删除匹配内容。",
                    },
                },
                "required": ["path", "old_text", "new_text"],
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
        """替换首次精确匹配并返回规范化路径与替换次数。"""

        path = self._read_nonempty_text(arguments, "path")
        old_text = self._read_nonempty_text(arguments, "old_text")
        new_text = self._read_text(arguments, "new_text")
        target_file = self._workspace.resolve_file(path)
        text = read_utf8_text(target_file, path)
        if old_text not in text:
            raise ToolExecutionError(f"文件中未找到要替换的文本：{path}。")

        try:
            updated_text = text.replace(old_text, new_text, 1)
            target_file.write_bytes(updated_text.encode("utf-8"))
        except OSError as error:
            raise ToolExecutionError(f"无法写入文件：{path}。") from error
        return {
            "path": target_file.relative_to(self._workspace.root).as_posix(),
            "replacements": 1,
        }

    @staticmethod
    def _read_nonempty_text(arguments: Mapping[str, object], field_name: str) -> str:
        value = EditFileTool._read_text(arguments, field_name)
        if not value:
            raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")
        return value

    @staticmethod
    def _read_text(arguments: Mapping[str, object], field_name: str) -> str:
        value = arguments.get(field_name)
        if not isinstance(value, str):
            raise ToolValidationError(f"字段“{field_name}”必须是字符串。")
        return value
