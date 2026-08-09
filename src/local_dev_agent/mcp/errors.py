"""MCP 领域向调用方暴露的可诊断异常。"""


class McpError(ValueError):
    """MCP 配置或协议数据不符合本地安全边界。"""


class McpNameValidationError(McpError):
    """MCP 服务名、工具名或组合后的公开名不安全。"""


class McpToolDefinitionError(McpError):
    """MCP Server 返回的工具定义无法安全适配到本地工具体系。"""


class McpProtocolError(RuntimeError):
    """MCP 传输层返回了不符合领域契约的结果。"""


class McpConnectionError(McpProtocolError):
    """无法建立或维持一次 MCP Server 连接。"""


class McpToolCallError(McpProtocolError):
    """外部 MCP 工具调用失败。"""
