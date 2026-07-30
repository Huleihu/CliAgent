"""Scheduler 与 Queue Processor 之间的进程内、线程安全 Trigger Queue。"""

from collections import deque
from threading import Lock

from .schema import CronTrigger


class InMemoryCronTriggerQueue:
    """以 FIFO 传递不可变触发快照，忙碌时允许处理器保留队首。"""

    def __init__(self) -> None:
        self._triggers: deque[CronTrigger] = deque()
        self._lock = Lock()

    def enqueue(self, trigger: CronTrigger) -> None:
        """写入一个已到期触发，拒绝非领域对象。"""

        if not isinstance(trigger, CronTrigger):
            raise TypeError("Cron 触发队列只能保存 CronTrigger 对象。")
        with self._lock:
            self._triggers.append(trigger)

    def peek(self) -> CronTrigger | None:
        """读取但不消费队首触发，供后续空闲检测使用。"""

        with self._lock:
            return self._triggers[0] if self._triggers else None

    def acknowledge(self, trigger: CronTrigger) -> None:
        """只确认当前队首同一快照，避免并发处理器误删触发。"""

        if not isinstance(trigger, CronTrigger):
            raise TypeError("Cron 触发队列只能确认 CronTrigger 对象。")
        with self._lock:
            if not self._triggers or self._triggers[0] != trigger:
                raise ValueError("只能确认当前 Cron 触发队列的队首触发。")
            self._triggers.popleft()
