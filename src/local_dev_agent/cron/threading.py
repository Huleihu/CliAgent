"""Cron Scheduler 的可替换等待与 daemon 线程运行适配器。"""

from collections.abc import Callable
from threading import Event, Thread

from .ports import CronThreadFactory, CronWaiter
from .scheduler import CronScheduler


class EventCronWaiter:
    """使用停止事件等待固定间隔，停止时立即返回而不额外 sleep。"""

    def wait(self, stop_event: Event, timeout_seconds: float) -> bool:
        """等待到超时或停止；返回 Event.wait 的停止结果。"""

        return stop_event.wait(timeout_seconds)


class DaemonCronThreadFactory:
    """创建并立即启动不会阻止 CLI 退出的 daemon 线程。"""

    def start(self, *, target: Callable[[], None], name: str) -> Thread:
        """启动命名线程，便于日志和线程诊断。"""

        thread = Thread(target=target, daemon=True, name=name)
        thread.start()
        return thread


class CronSchedulerRunner:
    """持有停止事件并经可替换线程工厂托管 Scheduler 循环。"""

    def __init__(
        self,
        *,
        scheduler: CronScheduler,
        waiter: CronWaiter,
        thread_factory: CronThreadFactory,
    ) -> None:
        if not callable(getattr(scheduler, "run", None)):
            raise TypeError("scheduler 必须提供 run 方法。")
        if not callable(getattr(waiter, "wait", None)):
            raise TypeError("waiter 必须提供 wait 方法。")
        if not callable(getattr(thread_factory, "start", None)):
            raise TypeError("thread_factory 必须提供 start 方法。")
        self._scheduler = scheduler
        self._waiter = waiter
        self._thread_factory = thread_factory
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> Thread:
        """只启动一次后台循环，防止重复线程重复判断同一任务。"""

        if self._thread is not None:
            raise RuntimeError("Cron Scheduler 已启动。")
        self._thread = self._thread_factory.start(
            target=self._run,
            name="cron-scheduler",
        )
        return self._thread

    def stop(self) -> None:
        """请求循环停止；不在此处 join，避免 CLI 退出被等待器阻塞。"""

        self._stop_event.set()

    def _run(self) -> None:
        self._scheduler.run(stop_event=self._stop_event, waiter=self._waiter)
