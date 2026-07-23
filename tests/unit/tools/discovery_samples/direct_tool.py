"""暴露工具实例的发现样例。"""

from local_dev_agent.tools import FakeTool, ToolDefinition


tool = FakeTool(
    definition=ToolDefinition(
        name="direct_tool",
        description="直接暴露的测试工具。",
        parameters={"type": "object", "properties": {}},
    ),
    result={"source": "direct"},
)
