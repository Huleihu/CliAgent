"""Hook 契约与后续执行边界产生的异常。"""


class HookValidationError(ValueError):
    """当 Hook 契约字段不符合约束时抛出。"""


class HookAlreadyExistsError(ValueError):
    """当同一事件重复注册同名 Hook 时抛出。"""

    def __init__(self, *, event: str, hook_name: str) -> None:
        super().__init__(f"事件“{event}”已注册 Hook“{hook_name}”，不能重复注册。")
        self.event = event
        self.hook_name = hook_name


class HookExecutionError(RuntimeError):
    """当 Hook 回调异常或没有返回约定结果时抛出。"""

    def __init__(self, *, event: str, hook_name: str, reason: str) -> None:
        super().__init__(f"事件“{event}”的 Hook“{hook_name}”执行失败：{reason}。")
        self.event = event
        self.hook_name = hook_name
