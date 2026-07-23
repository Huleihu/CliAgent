"""普通 Python 函数到受控工具端口的适配器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .ports import Tool
from .schema import ToolDefinition


class FunctionTool(Tool):
    """将无状态函数包装为工具，具体安全决策仍由执行器负责。"""

    def __init__(
        self,
        *,
        definition: ToolDefinition,
        function: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        if not callable(function):
            raise TypeError("工具函数必须可调用。")
        self._definition = definition
        self._function = function

    @property
    def definition(self) -> ToolDefinition:
        """返回包装函数对应的静态工具定义。"""

        return self._definition

    def run(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        """调用业务函数，返回值由执行器统一校验。"""

        return self._function(arguments)
