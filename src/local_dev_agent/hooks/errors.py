"""Hook 契约与后续执行边界产生的异常。"""


class HookValidationError(ValueError):
    """当 Hook 契约字段不符合约束时抛出。"""
