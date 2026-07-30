"""后台任务领域的可诊断错误。"""


class InvalidBackgroundTaskTransitionError(ValueError):
    """后台任务请求了当前状态不允许的生命周期变更。"""

    def __init__(self, *, task_id: str, status: str, target_status: str) -> None:
        super().__init__(
            f"后台任务“{task_id}”当前状态为“{status}”，不能转换为“{target_status}”。"
        )


class BackgroundTaskAlreadyExistsError(ValueError):
    """后台任务仓储拒绝重复写入相同标识。"""

    def __init__(self, *, task_id: str) -> None:
        super().__init__(f"后台任务“{task_id}”已存在。")


class BackgroundTaskNotFoundError(ValueError):
    """后台任务仓储找不到需要替换的既有任务。"""

    def __init__(self, *, task_id: str) -> None:
        super().__init__(f"后台任务“{task_id}”不存在。")


class CommandExecutionTimeoutError(TimeoutError):
    """命令超过受控执行时限而被执行适配器终止。"""

    def __init__(self, *, timeout_seconds: float) -> None:
        super().__init__(f"命令执行超过 {timeout_seconds:g} 秒时限。")
