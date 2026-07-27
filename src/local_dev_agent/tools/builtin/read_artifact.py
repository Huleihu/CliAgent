"""按受控 Artifact 引用分段回填已保存的大工具结果。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.context import ArtifactReadError, ToolResultArtifactReader

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


class ReadArtifactTool(Tool):
    """只通过 ArtifactReader 读取已保存结果，绝不解释模型提供的文件路径。"""

    _DEFAULT_MAX_CHARACTERS = 4_000
    _MAX_MAX_CHARACTERS = 12_000

    def __init__(self, reader: ToolResultArtifactReader) -> None:
        if not hasattr(reader, "read_text_page"):
            raise TypeError("reader 必须提供 read_text_page 方法。")
        self._reader = reader
        self._definition = ToolDefinition(
            name="read_artifact",
            description="按 artifact_ref 分段读取已保存的大工具结果；不能读取任意文件路径。",
            parameters={
                "type": "object",
                "properties": {
                    "artifact_ref": {
                        "type": "string",
                        "description": "工具结果中返回的精确 artifact_ref。",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "正文字符偏移量，从 0 开始，默认 0。",
                    },
                    "max_characters": {
                        "type": "integer",
                        "description": "本次最多返回的正文字符数，默认 4000，最大 12000。",
                    },
                },
                "required": ["artifact_ref"],
            },
            tags=("artifact", "read_only"),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回模型可见的受控 Artifact 读取定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """将经校验的有限分页转为 JSON 原生工具结果。"""

        artifact_ref = arguments.get("artifact_ref")
        if not isinstance(artifact_ref, str) or not artifact_ref.strip():
            raise ToolValidationError("字段“artifact_ref”必须是非空字符串。")
        offset = self._read_nonnegative_integer(arguments, "offset", default=0)
        max_characters = self._read_positive_integer(
            arguments,
            "max_characters",
            default=self._DEFAULT_MAX_CHARACTERS,
            maximum=self._MAX_MAX_CHARACTERS,
        )
        try:
            page = self._reader.read_text_page(
                artifact_ref=artifact_ref,
                offset=offset,
                max_characters=max_characters,
            )
        except ArtifactReadError as error:
            raise ToolExecutionError(str(error)) from error
        return {
            "artifact_ref": page.artifact_ref,
            "content": page.content,
            "offset": page.offset,
            "next_offset": page.next_offset,
            "total_characters": page.total_characters,
            "truncated": page.truncated,
        }

    @staticmethod
    def _read_nonnegative_integer(
        arguments: Mapping[str, object],
        field_name: str,
        *,
        default: int,
    ) -> int:
        value = arguments.get(field_name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ToolValidationError(f"字段“{field_name}”必须是非负整数。")
        return value

    @staticmethod
    def _read_positive_integer(
        arguments: Mapping[str, object],
        field_name: str,
        *,
        default: int,
        maximum: int,
    ) -> int:
        value = arguments.get(field_name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ToolValidationError(f"字段“{field_name}”必须是正整数。")
        if value > maximum:
            raise ToolValidationError(f"字段“{field_name}”不能大于 {maximum}。")
        return value
