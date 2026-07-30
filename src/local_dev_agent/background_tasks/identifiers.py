"""后台任务标识的进程内生成适配器。"""

from threading import Lock


class SequentialBackgroundTaskIdGenerator:
    """以进程内递增序号生成便于终端识别的后台任务标识。"""

    def __init__(self, *, prefix: str = "bg_", start: int = 1, width: int = 4) -> None:
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError("字段“prefix”必须是非空字符串。")
        if isinstance(start, bool) or not isinstance(start, int) or start < 1:
            raise ValueError("字段“start”必须是大于或等于 1 的整数。")
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise ValueError("字段“width”必须是大于或等于 1 的整数。")
        self._prefix = prefix
        self._next_value = start
        self._width = width
        self._lock = Lock()

    def new_task_id(self) -> str:
        """在线程互斥下获取下一个序号，避免并发派发出现重复标识。"""

        with self._lock:
            value = self._next_value
            self._next_value += 1
        return f"{self._prefix}{value:0{self._width}d}"
