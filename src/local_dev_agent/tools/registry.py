"""运行时可用工具的注册和查询。"""

from collections.abc import Iterable
from threading import RLock

from .errors import ToolAlreadyExistsError, ToolNotFoundError
from .ports import Tool
from .schema import ToolDefinition


class ToolRegistry:
    """维护唯一命名的工具集合，不承担导入或执行职责。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = RLock()

    def register(self, tool: Tool) -> None:
        """注册一个工具，拒绝同名覆盖以保护既有能力边界。"""

        self.register_many((tool,))

    def register_many(self, tools: Iterable[Tool]) -> None:
        """原子注册一组工具；任一名称冲突时不改变现有工具池。"""

        candidates = tuple(tools)
        if not all(isinstance(tool, Tool) for tool in candidates):
            raise TypeError("只能注册 Tool 类型的对象。")
        names = tuple(tool.definition.name for tool in candidates)
        with self._lock:
            existing_or_duplicate_names = set(self._tools).intersection(names)
            if existing_or_duplicate_names:
                raise ToolAlreadyExistsError(tool_name=sorted(existing_or_duplicate_names)[0])
            if len(names) != len(set(names)):
                duplicate_name = next(name for name in names if names.count(name) > 1)
                raise ToolAlreadyExistsError(tool_name=duplicate_name)
            self._tools.update({tool.definition.name: tool for tool in candidates})

    def get(self, name: str) -> Tool:
        """按名称取回已注册工具。"""

        with self._lock:
            try:
                return self._tools[name]
            except KeyError as error:
                raise ToolNotFoundError(tool_name=name) from error

    def list_definitions(self, *, tags: Iterable[str] | None = None) -> tuple[ToolDefinition, ...]:
        """稳定导出可暴露给模型的工具定义，可按任一标签过滤。"""

        expected_tags = frozenset(tags or ())
        with self._lock:
            definitions = tuple(
                definition
                for definition in (tool.definition for tool in self._tools.values())
                if not expected_tags or expected_tags.intersection(definition.tags)
            )
        return tuple(sorted(definitions, key=lambda definition: definition.name))
