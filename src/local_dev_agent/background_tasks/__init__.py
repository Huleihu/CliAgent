"""S13 后台任务的领域契约与可替换端口。"""

from .errors import (
    BackgroundTaskAlreadyExistsError,
    BackgroundTaskNotFoundError,
    CommandExecutionTimeoutError,
    InvalidBackgroundTaskTransitionError,
)
from .identifiers import SequentialBackgroundTaskIdGenerator
from .in_memory import InMemoryBackgroundTaskRepository
from .notifications import BackgroundTaskNotificationSource
from .policy import BackgroundExecutionPolicy
from .ports import (
    BackgroundTaskExecutionService,
    BackgroundTaskIdGenerator,
    BackgroundTaskRepository,
    CommandRunner,
)
from .service import ThreadedBackgroundTaskService
from .schema import BackgroundTask, BackgroundTaskStatus, CommandExecutionResult
from .subprocess_runner import SubprocessCommandRunner

__all__ = [
    "BackgroundTask",
    "BackgroundTaskAlreadyExistsError",
    "BackgroundTaskExecutionService",
    "BackgroundTaskIdGenerator",
    "BackgroundTaskNotFoundError",
    "BackgroundTaskNotificationSource",
    "BackgroundTaskRepository",
    "BackgroundTaskStatus",
    "BackgroundExecutionPolicy",
    "CommandExecutionResult",
    "CommandExecutionTimeoutError",
    "CommandRunner",
    "InvalidBackgroundTaskTransitionError",
    "InMemoryBackgroundTaskRepository",
    "SequentialBackgroundTaskIdGenerator",
    "SubprocessCommandRunner",
    "ThreadedBackgroundTaskService",
]
