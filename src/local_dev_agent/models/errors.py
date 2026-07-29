"""模型 Provider 之间可共享的运行时错误语义。"""

from math import isfinite


class ModelContextWindowExceededError(RuntimeError):
    """当 Provider 明确拒绝过大的输入上下文或请求体时抛出。"""


class ModelTransientError(RuntimeError):
    """表示稍后重试可能成功的 Provider 瞬态故障。"""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        """保存 Provider 建议的等待时间，供上层恢复策略统一决策。"""

        if retry_after_seconds is not None and (
            isinstance(retry_after_seconds, bool)
            or not isinstance(retry_after_seconds, int | float)
            or not isfinite(retry_after_seconds)
            or retry_after_seconds < 0
        ):
            raise ValueError("字段“retry_after_seconds”必须是非负有限数值或 None。")
        super().__init__(message)
        self.retry_after_seconds = (
            float(retry_after_seconds)
            if retry_after_seconds is not None
            else None
        )


class ModelConnectionError(ModelTransientError):
    """当 Provider 请求因网络连接故障未正常完成时抛出。"""


class ModelTimeoutError(ModelConnectionError):
    """当 Provider 请求因连接或响应超时未完成时抛出。"""


class ModelRateLimitError(ModelTransientError):
    """当 Provider 明确以 HTTP 429 拒绝当前请求速率时抛出。"""


class ModelOverloadedError(ModelTransientError):
    """当 Provider 明确以 HTTP 529 表示服务过载时抛出。"""
