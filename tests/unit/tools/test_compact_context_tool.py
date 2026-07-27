from local_dev_agent.tools import (
    CONTEXT_COMPACTION_TOOL_TAG,
    ToolCallRequest,
    ToolExecutor,
    ToolRegistry,
)
from local_dev_agent.tools.builtin import CompactContextTool


def test_compact_context_tool_only_returns_a_control_request() -> None:
    tool = CompactContextTool()

    result = tool.run({})

    assert tool.definition.name == "compact"
    assert tool.definition.tags == (CONTEXT_COMPACTION_TOOL_TAG,)
    assert tool.definition.parameters == {"type": "object", "properties": {}}
    assert result == {"requested": True}


def test_compact_context_tool_reuses_normal_argument_validation() -> None:
    registry = ToolRegistry()
    registry.register(CompactContextTool())

    result = ToolExecutor(registry).execute(
        ToolCallRequest(name="compact", arguments={"unexpected": True}, call_id="toolu-1")
    )

    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ToolValidationError"
