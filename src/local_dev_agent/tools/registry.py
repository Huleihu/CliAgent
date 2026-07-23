"""运行时可用工具的注册和查询。"""

from collections.abc import Iterable

from .errors import ToolAlreadyExistsError, ToolNotFoundError
from .ports import Tool
from .schema import ToolDefinition


class ToolRegistry:
    """维护唯一命名的工具集合，不承担导入或执行职责。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具，拒绝同名覆盖以保护既有能力边界。"""

        if not isinstance(tool, Tool):
            raise TypeError("只能注册 Tool 类型的对象。")
        if tool.definition.name in self._tools:
            raise ToolAlreadyExistsError(tool_name=tool.definition.name)
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool:
        """按名称取回已注册工具。"""

        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(tool_name=name) from error

    def list_definitions(self, *, tags: Iterable[str] | None = None) -> tuple[ToolDefinition, ...]:
        """稳定导出可暴露给模型的工具定义，可按任一标签过滤。"""

        expected_tags = frozenset(tags or ())
        definitions = tuple(
            definition
            for definition in (tool.definition for tool in self._tools.values())
            if not expected_tags or expected_tags.intersection(definition.tags)
        )
        return tuple(sorted(definitions, key=lambda definition: definition.name))
