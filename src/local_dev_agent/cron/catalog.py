"""合并 durable 与 session-only 定义仓储的应用适配器。"""

from .errors import CronTaskAlreadyExistsError
from .ports import CronTaskRepository
from .schema import CronTask, CronTaskScope


class CronTaskCatalog:
    """按 scope 路由读写，向 Scheduler 暴露单一一致的定义视图。"""

    def __init__(
        self,
        *,
        session_repository: CronTaskRepository,
        durable_repository: CronTaskRepository,
    ) -> None:
        self._require_repository("session_repository", session_repository)
        self._require_repository("durable_repository", durable_repository)
        self._session_repository = session_repository
        self._durable_repository = durable_repository

    def add(self, task: CronTask) -> CronTask:
        """新增定义前检查跨作用域标识冲突。"""

        if self.get(task.task_id) is not None:
            raise CronTaskAlreadyExistsError(task_id=task.task_id)
        return self._repository_for(task.scope).add(task)

    def get(self, task_id: str) -> CronTask | None:
        """从两个作用域读取唯一标识的定义。"""

        return self._session_repository.get(task_id) or self._durable_repository.get(task_id)

    def list_visible_to_session(self, session_id: str) -> tuple[CronTask, ...]:
        """稳定合并当前 Session 的私有定义和工作区 durable 定义。"""

        tasks = (
            *self._durable_repository.list_visible_to_session(session_id),
            *self._session_repository.list_visible_to_session(session_id),
        )
        task_ids = tuple(task.task_id for task in tasks)
        if len(set(task_ids)) != len(task_ids):
            duplicate = next(task_id for task_id in task_ids if task_ids.count(task_id) > 1)
            raise CronTaskAlreadyExistsError(task_id=duplicate)
        return tuple(sorted(tasks, key=lambda task: (task.created_at, task.task_id)))

    def replace(self, task: CronTask) -> CronTask:
        """将防重分钟等新快照写回其原始作用域。"""

        return self._repository_for(task.scope).replace(task)

    def remove(self, task_id: str) -> CronTask | None:
        """按已找到定义的作用域删除，避免误删同名的另一侧条目。"""

        task = self.get(task_id)
        return self._repository_for(task.scope).remove(task_id) if task is not None else None

    def _repository_for(self, scope: CronTaskScope) -> CronTaskRepository:
        if scope is CronTaskScope.SESSION_ONLY:
            return self._session_repository
        return self._durable_repository

    @staticmethod
    def _require_repository(name: str, repository: CronTaskRepository) -> None:
        required = ("add", "get", "list_visible_to_session", "replace", "remove")
        if not all(callable(getattr(repository, method, None)) for method in required):
            raise TypeError(f"{name} 必须提供 CronTaskRepository 的全部方法。")
