"""Team Runner 使用的进程内 Event 调度器、等待器和 daemon 线程适配器。"""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock, Thread


class EventTeamDispatcher:
    """将持久收件箱变更转换为进程内成员唤醒，不保存业务状态。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: dict[str, Event] = {}

    def register(self, *, member_id: str) -> Event:
        """为成员返回稳定 Event；同一成员的多个注册者共享同一唤醒信号。"""

        with self._lock:
            return self._events.setdefault(member_id, Event())

    def unregister(self, *, member_id: str, wake_event: Event) -> None:
        """避免旧 Runner 停止时误删后来注册者仍在使用的 Event。"""

        with self._lock:
            if self._events.get(member_id) is wake_event:
                self._events.pop(member_id)

    def signal(self, *, member_id: str) -> None:
        """唤醒已注册成员；尚未运行的成员仍由后续轮询读取持久收件箱。"""

        with self._lock:
            wake_event = self._events.get(member_id)
        if wake_event is not None:
            wake_event.set()


class EventTeamWaiter:
    """以成员 Event 等待，停止时由 Runner 同时设置两个 Event 立即退出。"""

    def wait(
        self,
        *,
        stop_event: Event,
        wake_event: Event,
        timeout_seconds: float,
    ) -> bool:
        """等待唤醒或固定检查间隔，随后清除本次唤醒信号。"""

        wake_event.wait(timeout_seconds)
        wake_event.clear()
        return stop_event.is_set()


class DaemonTeamThreadFactory:
    """启动不阻塞 CLI 退出的命名 daemon 线程。"""

    def start(self, *, target: Callable[[], None], name: str) -> Thread:
        """创建并立刻启动线程，线程目标始终由 Runner 提供。"""

        thread = Thread(target=target, daemon=True, name=name)
        thread.start()
        return thread
