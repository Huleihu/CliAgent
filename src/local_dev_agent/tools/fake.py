"""用于工具框架测试的确定性工具实现。"""

from collections.abc import Mapping

from .ports import Tool
from .schema import ToolDefinition, ToolExecutionContext


class FakeTool(Tool):
    """记录调用参数并返回预设结果，避免测试接触外部能力。"""

    def __init__(self, *, definition: ToolDefinition, result: Mapping[str, object]) -> None:
        self._definition = definition
        self._result = dict(result)
        self.calls: list[Mapping[str, object]] = []
        self.contexts: list[ToolExecutionContext | None] = []

    @property
    def definition(self) -> ToolDefinition:
        """返回测试工具的定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """记录参数与执行上下文后返回预设数据。"""

        self.calls.append(dict(arguments))
        self.contexts.append(context)
        return dict(self._result)
