"""Cron 定义注册、查询与取消的应用服务。"""

from __future__ import annotations

from .errors import CronTaskAlreadyExistsError, CronTaskNotFoundError
from .expression import parse_cron_expression
from .ports import CronClock, CronTaskIdGenerator, CronTaskRepository
from .schema import CronTask, CronTaskScope


class CronTaskService:
    """按作用域路由定义仓储，保持表达式校验先于任何持久化副作用。"""

    def __init__(
        self,
        *,
        session_repository: CronTaskRepository,
        durable_repository: CronTaskRepository,
        id_generator: CronTaskIdGenerator,
        clock: CronClock,
    ) -> None:
        self._require_repository("session_repository", session_repository)
        self._require_repository("durable_repository", durable_repository)
        if not callable(getattr(id_generator, "new_task_id", None)):
            raise TypeError("id_generator 必须提供 new_task_id 方法。")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须提供 now 方法。")
        self._session_repository = session_repository
        self._durable_repository = durable_repository
        self._id_generator = id_generator
        self._clock = clock

    def schedule(
        self,
        *,
        session_id: str,
        cron: str,
        prompt: str,
        recurring: bool = True,
        durable: bool = False,
    ) -> CronTask:
        """校验后注册定义；durable 只表示定义可在进程重启后恢复。"""

        self._require_session_id(session_id)
        if not isinstance(recurring, bool):
            raise ValueError("字段“recurring”必须是布尔值。")
        if not isinstance(durable, bool):
            raise ValueError("字段“durable”必须是布尔值。")
        expression = parse_cron_expression(cron)
        task_id = self._id_generator.new_task_id()
        if self._find_task(task_id) is not None:
            raise CronTaskAlreadyExistsError(task_id=task_id)
        scope = CronTaskScope.DURABLE if durable else CronTaskScope.SESSION_ONLY
        task = CronTask.create(
            task_id=task_id,
            cron=expression.source,
            prompt=prompt,
            recurring=recurring,
            scope=scope,
            owner_session_id=None if durable else session_id,
            created_at=self._clock.now(),
        )
        return self._repository_for(scope).add(task)

    def list_for_session(self, *, session_id: str) -> tuple[CronTask, ...]:
        """稳定合并工作区 durable 定义与当前 Session 的内存定义。"""

        self._require_session_id(session_id)
        tasks = (
            *self._durable_repository.list_visible_to_session(session_id),
            *self._session_repository.list_visible_to_session(session_id),
        )
        task_ids = tuple(task.task_id for task in tasks)
        if len(set(task_ids)) != len(task_ids):
            duplicate_task_id = next(
                task_id for task_id in task_ids if task_ids.count(task_id) > 1
            )
            raise CronTaskAlreadyExistsError(task_id=duplicate_task_id)
        return tuple(sorted(tasks, key=lambda task: (task.created_at, task.task_id)))

    def cancel(self, *, session_id: str, task_id: str) -> CronTask:
        """取消当前 Session 自己的 session-only 定义或工作区 durable 定义。"""

        self._require_session_id(session_id)
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("字段“task_id”必须是非空字符串。")
        task = self._find_task(task_id)
        if task is None or not task.is_visible_to(session_id):
            raise CronTaskNotFoundError(task_id=task_id)
        removed_task = self._repository_for(task.scope).remove(task.task_id)
        if removed_task is None:
            raise CronTaskNotFoundError(task_id=task.task_id)
        return removed_task

    def _find_task(self, task_id: str) -> CronTask | None:
        """在两个作用域中查找标识，维持跨仓储唯一性。"""

        return self._session_repository.get(task_id) or self._durable_repository.get(task_id)

    def _repository_for(self, scope: CronTaskScope) -> CronTaskRepository:
        """按不可变作用域选择唯一写入目标。"""

        if scope is CronTaskScope.SESSION_ONLY:
            return self._session_repository
        return self._durable_repository

    @staticmethod
    def _require_repository(name: str, repository: CronTaskRepository) -> None:
        """在组合根之外也尽早诊断不完整的结构化仓储。"""

        required_methods = (
            "add",
            "get",
            "list_visible_to_session",
            "replace",
            "remove",
        )
        if not all(callable(getattr(repository, method_name, None)) for method_name in required_methods):
            raise TypeError(f"{name} 必须提供 CronTaskRepository 的全部方法。")

    @staticmethod
    def _require_session_id(session_id: str) -> None:
        """保证 session-only 作用域和可见性判断始终有明确边界。"""

        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("字段“session_id”必须是非空字符串。")
