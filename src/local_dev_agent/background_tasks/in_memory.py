"""后台任务的进程内、线程安全仓储适配器。"""

from threading import Lock

from .errors import BackgroundTaskAlreadyExistsError, BackgroundTaskNotFoundError
from .schema import BackgroundTask


def _require_task_id(task_id: str) -> None:
    """拒绝无法安全定位仓储条目的空白标识。"""

    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("字段“task_id”必须是非空字符串。")


def _require_session_id(session_id: str) -> None:
    """拒绝无法隔离查询范围的空白 Session 标识。"""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("字段“session_id”必须是非空字符串。")


class InMemoryBackgroundTaskRepository:
    """使用互斥锁保存当前进程内的不可变后台任务快照。"""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = Lock()

    def add(self, task: BackgroundTask) -> BackgroundTask:
        """新增运行中任务，拒绝意外覆盖同标识快照。"""

        if not isinstance(task, BackgroundTask):
            raise TypeError("后台任务仓储只能保存 BackgroundTask 对象。")
        with self._lock:
            if task.task_id in self._tasks:
                raise BackgroundTaskAlreadyExistsError(task_id=task.task_id)
            self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        """按标识读取不可变快照，不暴露内部可变容器。"""

        _require_task_id(task_id)
        with self._lock:
            return self._tasks.get(task_id)

    def list_for_session(self, session_id: str) -> tuple[BackgroundTask, ...]:
        """按创建时间和标识稳定返回一个 Session 的任务快照。"""

        _require_session_id(session_id)
        with self._lock:
            tasks = tuple(
                task for task in self._tasks.values() if task.session_id == session_id
            )
        return tuple(sorted(tasks, key=lambda task: (task.created_at, task.task_id)))

    def replace(self, task: BackgroundTask) -> BackgroundTask:
        """以同一任务身份的新快照原子替换既有任务。"""

        if not isinstance(task, BackgroundTask):
            raise TypeError("后台任务仓储只能保存 BackgroundTask 对象。")
        with self._lock:
            previous = self._tasks.get(task.task_id)
            if previous is None:
                raise BackgroundTaskNotFoundError(task_id=task.task_id)
            if _identity_fields(task) != _identity_fields(previous):
                raise ValueError("替换后台任务时不能改变任务归属、调用关联或命令。")
            self._tasks[task.task_id] = task
        return task


def _identity_fields(task: BackgroundTask) -> tuple[str, str, str, str, str, object]:
    """提取替换时不可改变的任务身份字段。"""

    return (
        task.task_id,
        task.session_id,
        task.run_id,
        task.tool_call_id,
        task.command,
        task.created_at,
    )
