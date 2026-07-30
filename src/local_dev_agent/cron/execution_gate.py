"""Cron Queue Processor 使用的进程内执行租约适配器。"""

from threading import Lock


class LockCronExecutionGate:
    """用非阻塞互斥锁确保同一时刻只交付一个 Agent Run。"""

    def __init__(self) -> None:
        self._lock = Lock()

    def try_acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()
