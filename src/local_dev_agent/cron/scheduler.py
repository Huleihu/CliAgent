"""只负责到期判断和 Trigger 入队的 Cron Scheduler。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event

from .expression import cron_matches, parse_cron_expression
from .ports import CronClock, CronTaskRepository, CronTriggerQueue, CronWaiter
from .schema import CronTask, CronTrigger

logger = logging.getLogger(__name__)


class CronScheduler:
    """不调用 Agent 的调度器：匹配定义、写队列、更新防重或删除一次性定义。"""

    def __init__(
        self,
        *,
        repository: CronTaskRepository,
        trigger_queue: CronTriggerQueue,
        clock: CronClock,
        session_id: str,
        check_interval_seconds: float = 1.0,
    ) -> None:
        if not callable(getattr(repository, "list_visible_to_session", None)) or not callable(
            getattr(repository, "replace", None)
        ) or not callable(getattr(repository, "remove", None)):
            raise TypeError("repository 必须提供 CronTaskRepository 的调度方法。")
        if not callable(getattr(trigger_queue, "enqueue", None)):
            raise TypeError("trigger_queue 必须提供 enqueue 方法。")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须提供 now 方法。")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("字段“session_id”必须是非空字符串。")
        if isinstance(check_interval_seconds, bool) or not isinstance(check_interval_seconds, (int, float)) or check_interval_seconds <= 0:
            raise ValueError("字段“check_interval_seconds”必须是正数。")
        self._repository = repository
        self._trigger_queue = trigger_queue
        self._clock = clock
        self._session_id = session_id.strip()
        self._check_interval_seconds = float(check_interval_seconds)
        self._last_enqueued_minutes: dict[str, datetime] = {}
        self._retired_task_ids: set[str] = set()

    def tick(self) -> tuple[CronTrigger, ...]:
        """检查当前分钟并写入所有到期任务；单条坏定义不影响其他任务。"""

        now = self._clock.now()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("clock.now 必须返回带时区的 datetime。")
        minute = now.replace(second=0, microsecond=0)
        fired: list[CronTrigger] = []
        for task in self._repository.list_visible_to_session(self._session_id):
            try:
                trigger = self._enqueue_if_due(task=task, now=now, minute=minute)
            except Exception:
                logger.warning("检查 Cron 任务到期状态失败，已跳过该任务。", exc_info=True)
                continue
            if trigger is not None:
                fired.append(trigger)
        return tuple(fired)

    def run(self, *, stop_event: Event, waiter: CronWaiter) -> None:
        """在外部线程中重复检查；等待器可替换以消除测试中的真实 sleep。"""

        if not isinstance(stop_event, Event):
            raise TypeError("stop_event 必须是 Event 对象。")
        if not callable(getattr(waiter, "wait", None)):
            raise TypeError("waiter 必须提供 wait 方法。")
        while not stop_event.is_set():
            self.tick()
            if waiter.wait(stop_event, self._check_interval_seconds):
                return

    def _enqueue_if_due(
        self,
        *,
        task: CronTask,
        now: datetime,
        minute: datetime,
    ) -> CronTrigger | None:
        """对一个快照执行防重、匹配、入队及其后续定义状态更新。"""

        if not isinstance(task, CronTask):
            raise TypeError("Cron 任务仓储必须只返回 CronTask 对象。")
        minute_marker = minute.astimezone(timezone.utc)
        if (
            task.task_id in self._retired_task_ids
            or self._last_enqueued_minutes.get(task.task_id) == minute_marker
            or task.last_enqueued_minute == minute_marker
        ):
            return None
        expression = parse_cron_expression(task.cron)
        if not cron_matches(expression, now):
            return None
        trigger = CronTrigger.create(
            task=task,
            session_id=self._session_id,
            scheduled_minute=minute,
            enqueued_at=now,
        )
        self._trigger_queue.enqueue(trigger)
        # 入队已成功时先更新进程内状态，避免后续仓储故障导致同一分钟重复入队。
        self._last_enqueued_minutes[task.task_id] = minute_marker
        if task.recurring:
            self._repository.replace(task.mark_enqueued(minute=minute))
        else:
            self._retired_task_ids.add(task.task_id)
            self._repository.remove(task.task_id)
        return trigger
