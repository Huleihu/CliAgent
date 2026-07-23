"""修改运行时状态时产生的领域错误。"""


class InvalidRunTransitionError(ValueError):
    """当一次运行尝试进入其生命周期不允许的状态时抛出。"""

    def __init__(self, *, run_id: str, source_status: str, target_status: str) -> None:
        message = (
            f"运行“{run_id}”不能从状态“{source_status}”"
            f"跳转到“{target_status}”。"
        )
        super().__init__(message)
        self.run_id = run_id
        self.source_status = source_status
        self.target_status = target_status


class InvalidStepTransitionError(ValueError):
    """当一个步骤尝试进入其生命周期不允许的状态时抛出。"""

    def __init__(self, *, step_id: str, source_status: str, target_status: str) -> None:
        message = (
            f"步骤“{step_id}”不能从状态“{source_status}”"
            f"跳转到“{target_status}”。"
        )
        super().__init__(message)
        self.step_id = step_id
        self.source_status = source_status
        self.target_status = target_status
