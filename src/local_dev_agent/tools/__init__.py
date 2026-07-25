"""受控工具的契约、注册、发现与执行边界。"""

from .discovery import ToolDiscovery
from .executor import ToolExecutor
from .fake import FakeTool
from .function_tool import FunctionTool
from .ports import Tool
from .registry import ToolRegistry
from .schema import (
    DELEGATION_TOOL_TAG,
    ToolCallRequest,
    ToolCallResult,
    ToolDefinition,
    ToolExecutionContext,
)

__all__ = [
    "FakeTool",
    "FunctionTool",
    "DELEGATION_TOOL_TAG",
    "Tool",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolDefinition",
    "ToolDiscovery",
    "ToolExecutionContext",
    "ToolExecutor",
    "ToolRegistry",
]
