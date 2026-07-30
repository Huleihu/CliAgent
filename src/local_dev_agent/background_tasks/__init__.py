"""S13 后台任务的领域契约与可替换端口。"""

from .errors import (
    BackgroundTaskAlreadyExistsError,
    BackgroundTaskNotFoundError,
    InvalidBackgroundTaskTransitionError,
)
from .identifiers import SequentialBackgroundTaskIdGenerator
from .in_memory import InMemoryBackgroundTaskRepository
from .ports import (
    BackgroundTaskExecutionService,
    BackgroundTaskIdGenerator,
    BackgroundTaskRepository,
    CommandRunner,
)
from .service import ThreadedBackgroundTaskService
from .schema import BackgroundTask, BackgroundTaskStatus, CommandExecutionResult

__all__ = [
    "BackgroundTask",
    "BackgroundTaskAlreadyExistsError",
    "BackgroundTaskExecutionService",
    "BackgroundTaskIdGenerator",
    "BackgroundTaskNotFoundError",
    "BackgroundTaskRepository",
    "BackgroundTaskStatus",
    "CommandExecutionResult",
    "CommandRunner",
    "InvalidBackgroundTaskTransitionError",
    "InMemoryBackgroundTaskRepository",
    "SequentialBackgroundTaskIdGenerator",
    "ThreadedBackgroundTaskService",
]
