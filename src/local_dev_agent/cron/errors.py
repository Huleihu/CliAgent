"""Cron 调度领域和基础设施的稳定错误类型。"""

from pathlib import Path


class CronExpressionValidationError(ValueError):
    """当五段式 cron 表达式不属于首版安全子集时抛出。"""


class CronTaskRepositoryError(ValueError):
    """Cron 定义仓储产生的基础设施错误。"""


class CronTaskAlreadyExistsError(CronTaskRepositoryError):
    """新增定义时发现相同稳定标识已经存在时抛出。"""

    def __init__(self, *, task_id: str) -> None:
        super().__init__(f"Cron 任务“{task_id}”已存在，不能重复创建。")
        self.task_id = task_id


class CronTaskNotFoundError(CronTaskRepositoryError):
    """读取、替换或取消不存在的定义时抛出。"""

    def __init__(self, *, task_id: str) -> None:
        super().__init__(f"Cron 任务“{task_id}”不存在。")
        self.task_id = task_id


class CorruptedCronTaskFileError(CronTaskRepositoryError):
    """durable JSON 文件无法解析或版本化信封不受支持时抛出。"""

    def __init__(self, *, path: Path) -> None:
        super().__init__(f"Cron 任务文件“{path}”已损坏或格式不受支持。")
        self.path = path
