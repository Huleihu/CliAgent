"""S13 后台任务的领域契约与可替换端口。"""

from .errors import InvalidBackgroundTaskTransitionError
from .ports import BackgroundTaskIdGenerator, BackgroundTaskRepository, CommandRunner
from .schema import BackgroundTask, BackgroundTaskStatus, CommandExecutionResult

__all__ = [
    "BackgroundTask",
    "BackgroundTaskIdGenerator",
    "BackgroundTaskRepository",
    "BackgroundTaskStatus",
    "CommandExecutionResult",
    "CommandRunner",
    "InvalidBackgroundTaskTransitionError",
]
