"""工具框架产生的边界错误。"""


class ToolValidationError(ValueError):
    """当工具契约或调用数据不符合约束时抛出。"""


class ToolAlreadyExistsError(ValueError):
    """当注册表收到同名工具时抛出。"""

    def __init__(self, *, tool_name: str) -> None:
        super().__init__(f"工具“{tool_name}”已注册，不能重复注册。")
        self.tool_name = tool_name


class ToolNotFoundError(ValueError):
    """当调用请求引用未注册工具时抛出。"""

    def __init__(self, *, tool_name: str) -> None:
        super().__init__(f"找不到已注册的工具“{tool_name}”。")
        self.tool_name = tool_name


class ToolExecutionError(RuntimeError):
    """当工具执行或返回值不符合执行边界时抛出。"""


class ToolDiscoveryError(RuntimeError):
    """当受控工具包无法完成发现时抛出。"""
