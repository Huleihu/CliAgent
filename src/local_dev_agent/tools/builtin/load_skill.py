"""按精确名称将已扫描 Skill 正文回填给模型的只读工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.skills import SkillCatalog

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


class LoadSkillTool(Tool):
    """从启动时技能快照加载完整文档，不接受或解析文件路径。"""

    def __init__(self, catalog: SkillCatalog) -> None:
        if not isinstance(catalog, SkillCatalog):
            raise TypeError("技能目录必须是 SkillCatalog 对象。")
        self._catalog = catalog
        self._definition = ToolDefinition(
            name="load_skill",
            description="按技能名称加载完整 SKILL.md，用于需要详细规范或流程时。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能目录中展示的精确技能名称。",
                    },
                },
                "required": ["name"],
            },
            tags=("knowledge", "read_only"),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回父 Agent 可见的 Skill 加载工具定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """返回完整快照正文与受控相对目录，供后续文件工具定位资源。"""

        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolValidationError("字段“name”必须是非空字符串。")
        document = self._catalog.get_document(name)
        if document is None:
            raise ToolExecutionError(f"找不到可加载的技能“{name.strip()}”。")
        return {
            "name": document.metadata.name,
            "description": document.metadata.description,
            "source_directory": document.source_directory,
            "content": document.content,
        }
