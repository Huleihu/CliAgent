"""将后台任务终态适配为可供 Runtime 排出的文本通知。"""

from __future__ import annotations

from html import escape
from threading import Lock

from .ports import BackgroundTaskRepository
from .schema import BackgroundTask


class BackgroundTaskNotificationSource:
    """按 Session 一次性消费已结束后台任务，不直接写入对话存储。"""

    def __init__(self, repository: BackgroundTaskRepository) -> None:
        if not callable(getattr(repository, "list_for_session", None)):
            raise TypeError("后台任务仓储必须提供 list_for_session 方法。")
        self._repository = repository
        self._delivered_task_ids: set[str] = set()
        self._lock = Lock()

    def drain(self, *, session_id: str) -> tuple[str, ...]:
        """返回指定 Session 尚未通知的终态任务，并保证同一进程内只返回一次。"""

        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("字段“session_id”必须是非空字符串。")
        tasks = self._repository.list_for_session(session_id)
        with self._lock:
            ready_tasks = tuple(
                task
                for task in tasks
                if task.is_terminal and task.task_id not in self._delivered_task_ids
            )
            self._delivered_task_ids.update(task.task_id for task in ready_tasks)
        return tuple(_format_notification(task) for task in ready_tasks)


def _format_notification(task: BackgroundTask) -> str:
    """以受转义的结构化文本表达终态，不复用原始工具调用标识。"""

    summary = task.output_summary or ""
    failure_reason = task.failure_reason or ""
    exit_code = "" if task.exit_code is None else str(task.exit_code)
    return "\n".join(
        (
            "<task_notification>",
            f"  <task_id>{escape(task.task_id)}</task_id>",
            f"  <status>{escape(task.status.value)}</status>",
            f"  <command>{escape(task.command)}</command>",
            f"  <exit_code>{escape(exit_code)}</exit_code>",
            f"  <summary>{escape(summary)}</summary>",
            f"  <failure_reason>{escape(failure_reason)}</failure_reason>",
            "</task_notification>",
        )
    )
