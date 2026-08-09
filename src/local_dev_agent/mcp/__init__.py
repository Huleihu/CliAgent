"""S19 MCP 外接工具领域的公共契约。"""

from local_dev_agent.mcp.errors import (
    McpConnectionError,
    McpError,
    McpNameValidationError,
    McpProtocolError,
    McpToolCallError,
    McpToolDefinitionError,
)
from local_dev_agent.mcp.ports import (
    McpCallContext,
    McpCallResult,
    McpClient,
    McpClientConnector,
    McpServerCatalog,
    McpToolPool,
)
from local_dev_agent.mcp.schema import (
    McpServerConfiguration,
    McpToolAnnotations,
    McpToolDefinition,
)

__all__ = [
    "McpCallContext",
    "McpCallResult",
    "McpClient",
    "McpClientConnector",
    "McpConnectionError",
    "McpError",
    "McpNameValidationError",
    "McpProtocolError",
    "McpServerCatalog",
    "McpServerConfiguration",
    "McpToolAnnotations",
    "McpToolCallError",
    "McpToolDefinition",
    "McpToolDefinitionError",
    "McpToolPool",
]
