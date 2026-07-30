"""Cron 调度领域与后续基础设施适配器之间的稳定端口。"""

from collections.abc import Callable, Sequence
from datetime import datetime
from threading import Event, Thread
from typing import Protocol

from .schema import CronTask, CronTrigger


class CronTaskIdGenerator(Protocol):
    """为调度定义生成可替换的稳定任务标识。"""

    def new_task_id(self) -> str:
        """返回尚未写入仓储的新任务标识。"""


class CronTaskRepository(Protocol):
    """保存 cron 定义快照，不绑定内存、JSON 或其他基础设施。"""

    def add(self, task: CronTask) -> CronTask:
        """新增一个定义快照。"""

    def get(self, task_id: str) -> CronTask | None:
        """按标识读取定义；不存在时返回 None。"""

    def list_visible_to_session(self, session_id: str) -> Sequence[CronTask]:
        """稳定返回当前 Session 可见的 durable 与 session-only 定义。"""

    def replace(self, task: CronTask) -> CronTask:
        """以新的完整快照替换既有定义。"""

    def remove(self, task_id: str) -> CronTask | None:
        """删除指定定义，并返回被删除快照或 None。"""


class CronClock(Protocol):
    """提供可替换的带时区本地时间，供 Scheduler 判断表达式。"""

    def now(self) -> datetime:
        """返回一个带时区的当前时间。"""


class CronTriggerQueue(Protocol):
    """在 Scheduler 与 Queue Processor 之间传递已到期的触发快照。"""

    def enqueue(self, trigger: CronTrigger) -> None:
        """写入一个尚未交付的触发。"""

    def peek(self) -> CronTrigger | None:
        """读取队首触发但不消费，以便忙碌时保留交付机会。"""

    def acknowledge(self, trigger: CronTrigger) -> None:
        """确认并移除已经尝试交付的队首触发。"""


class CronWaiter(Protocol):
    """隔离调度循环等待，避免单元测试依赖真实 sleep。"""

    def wait(self, stop_event: Event, timeout_seconds: float) -> bool:
        """等待超时或停止事件；返回 True 表示应停止循环。"""


class CronThreadFactory(Protocol):
    """隔离 daemon 线程创建，允许测试同步接管线程目标。"""

    def start(self, *, target: Callable[[], None], name: str) -> Thread:
        """启动线程并返回其句柄。"""


class CronTriggerConsumer(Protocol):
    """接收已到期 Trigger 的交付端口，不绑定 Agent 或 Runtime。"""

    def consume(self, trigger: CronTrigger) -> None:
        """尝试交付一项已经由 Scheduler 产生的触发。"""


class CronExecutionGate(Protocol):
    """串行化定时 Agent 交付的非阻塞执行租约。"""

    def try_acquire(self) -> bool:
        """成功获得租约时返回 True；忙碌时不阻塞。"""

    def release(self) -> None:
        """释放此前成功获得的执行租约。"""


class CronTaskApplicationService(Protocol):
    """供工具层调用的 cron 注册、查询与取消用例。"""

    def schedule(self, *, session_id: str, cron: str, prompt: str, recurring: bool = True, durable: bool = False) -> CronTask:
        """注册新定义。"""

    def list_for_session(self, *, session_id: str) -> tuple[CronTask, ...]:
        """读取当前 Session 可见定义。"""

    def cancel(self, *, session_id: str, task_id: str) -> CronTask:
        """取消当前 Session 可访问的定义。"""
