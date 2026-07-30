"""Cron 调度领域的稳定错误类型。"""


class CronExpressionValidationError(ValueError):
    """当五段式 cron 表达式不属于首版安全子集时抛出。"""
