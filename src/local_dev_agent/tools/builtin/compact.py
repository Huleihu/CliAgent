"""由模型请求、但只能由 Runtime 实际执行的上下文压缩控制工具。"""

from __future__ import annotations

from collections.abc import Mapping

from ..ports import Tool
from ..schema import CONTEXT_COMPACTION_TOOL_TAG, ToolDefinition, ToolExecutionContext


class CompactContextTool(Tool):
    """只声明压缩意图，避免工具直接持有或改写消息历史。"""

    def __init__(self) -> None:
        self._definition = ToolDefinition(
            name="compact",
            description="请求 Runtime 在下一次模型调用前压缩当前上下文；不会修改原始会话历史。",
            parameters={"type": "object", "properties": {}},
            tags=(CONTEXT_COMPACTION_TOOL_TAG,),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回由父 Agent 调用的控制工具定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """确认收到请求；实际压缩始终由外层 Runtime 在下一轮执行。"""

        return {"requested": True}
