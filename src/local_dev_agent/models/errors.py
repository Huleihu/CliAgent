"""模型 Provider 之间可共享的运行时错误语义。"""


class ModelContextWindowExceededError(RuntimeError):
    """当 Provider 明确拒绝过大的输入上下文或请求体时抛出。"""

