"""session-only Cron 定义的进程内、线程安全仓储适配器。"""

from threading import Lock

from .errors import CronTaskAlreadyExistsError, CronTaskNotFoundError
from .schema import CronTask, CronTaskScope


def _require_task_id(task_id: str) -> str:
    """拒绝无法安全定位定义的空白标识。"""

    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("字段“task_id”必须是非空字符串。")
    return task_id.strip()


class InMemoryCronTaskRepository:
    """仅保存当前进程中 session-only 的不可变 cron 定义快照。"""

    def __init__(self) -> None:
        self._tasks: dict[str, CronTask] = {}
        self._lock = Lock()

    def add(self, task: CronTask) -> CronTask:
        """新增 session-only 定义，拒绝覆盖或错误作用域。"""

        self._require_session_only(task)
        with self._lock:
            if task.task_id in self._tasks:
                raise CronTaskAlreadyExistsError(task_id=task.task_id)
            self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> CronTask | None:
        """按标识读取快照，不暴露内部可变容器。"""

        with self._lock:
            return self._tasks.get(_require_task_id(task_id))

    def list_visible_to_session(self, session_id: str) -> tuple[CronTask, ...]:
        """按创建时间和标识稳定返回当前 Session 自己的定义。"""

        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("字段“session_id”必须是非空字符串。")
        with self._lock:
            tasks = tuple(
                task for task in self._tasks.values() if task.is_visible_to(session_id)
            )
        return tuple(sorted(tasks, key=lambda task: (task.created_at, task.task_id)))

    def replace(self, task: CronTask) -> CronTask:
        """以同一身份的新快照原子替换既有 session-only 定义。"""

        self._require_session_only(task)
        with self._lock:
            previous = self._tasks.get(task.task_id)
            if previous is None:
                raise CronTaskNotFoundError(task_id=task.task_id)
            if _identity_fields(previous) != _identity_fields(task):
                raise ValueError("替换 Cron 任务时不能改变作用域、归属、表达式或提示。")
            self._tasks[task.task_id] = task
        return task

    def remove(self, task_id: str) -> CronTask | None:
        """删除一个 session-only 定义；不存在时返回 None。"""

        with self._lock:
            return self._tasks.pop(_require_task_id(task_id), None)

    @staticmethod
    def _require_session_only(task: CronTask) -> None:
        """防止 durable 定义被误写入进程内 Session 仓储。"""

        if not isinstance(task, CronTask):
            raise TypeError("Cron 任务仓储只能保存 CronTask 对象。")
        if task.scope is not CronTaskScope.SESSION_ONLY:
            raise ValueError("内存 Cron 仓储只能保存 session-only 任务。")


def _identity_fields(task: CronTask) -> tuple[object, ...]:
    """提取替换时不得改变的任务定义字段。"""

    return (
        task.task_id,
        task.cron,
        task.prompt,
        task.recurring,
        task.scope,
        task.created_at,
        task.owner_session_id,
    )
