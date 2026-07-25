"""待办清单更新提醒的轻量运行时策略。"""


TODO_REMINDER_MESSAGE = "请在继续执行前检查并使用 todo_write 更新待办清单。"


class TodoReminderPolicy:
    """在连续工具轮次未更新待办时产生一次临时提醒。"""

    def __init__(self, *, max_tool_turns_without_update: int = 3) -> None:
        if max_tool_turns_without_update < 1:
            raise ValueError("待办提醒阈值必须大于或等于 1。")
        self._max_tool_turns_without_update = max_tool_turns_without_update
        self._tool_turns_without_update = 0

    @property
    def tool_turns_without_update(self) -> int:
        """返回自上次成功更新待办后的连续工具轮次数。"""

        return self._tool_turns_without_update

    def record_tool_turn(self, *, todo_updated: bool) -> None:
        """记录一轮工具执行；成功更新待办时重置连续计数。"""

        if todo_updated:
            self._tool_turns_without_update = 0
            return
        self._tool_turns_without_update += 1

    def consume_reminder(self) -> str | None:
        """达到阈值时返回一次提醒并重置计数，避免每轮重复注入。"""

        if self._tool_turns_without_update < self._max_tool_turns_without_update:
            return None
        self._tool_turns_without_update = 0
        return TODO_REMINDER_MESSAGE
