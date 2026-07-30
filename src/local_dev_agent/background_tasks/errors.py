"""后台任务领域的可诊断错误。"""


class InvalidBackgroundTaskTransitionError(ValueError):
    """后台任务请求了当前状态不允许的生命周期变更。"""

    def __init__(self, *, task_id: str, status: str, target_status: str) -> None:
        super().__init__(
            f"后台任务“{task_id}”当前状态为“{status}”，不能转换为“{target_status}”。"
        )

