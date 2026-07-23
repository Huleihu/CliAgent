"""暴露工具工厂的发现样例。"""

from local_dev_agent.tools import FakeTool, ToolDefinition


def create_tool() -> FakeTool:
    """构造供发现器调用的测试工具。"""

    return FakeTool(
        definition=ToolDefinition(
            name="factory_tool",
            description="工厂创建的测试工具。",
            parameters={"type": "object", "properties": {}},
        ),
        result={"source": "factory"},
    )
