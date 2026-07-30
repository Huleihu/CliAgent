"""将 Cron Trigger 交给组合根提供的执行回调。"""

from collections.abc import Callable

from .schema import CronTrigger


class SessionBoundCronTriggerConsumer:
    """只接受指定 Session 的 Trigger，避免跨会话执行 prompt。"""

    def __init__(
        self,
        *,
        session_id: str,
        run_prompt: Callable[[str], None],
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("字段“session_id”必须是非空字符串。")
        if not callable(run_prompt):
            raise TypeError("run_prompt 必须是可调用对象。")
        self._session_id = session_id.strip()
        self._run_prompt = run_prompt

    def consume(self, trigger: CronTrigger) -> None:
        """将已绑定的 prompt 交给外部执行器，不依赖 Runtime 实现。"""

        if not isinstance(trigger, CronTrigger):
            raise TypeError("trigger 必须是 CronTrigger 对象。")
        if trigger.session_id != self._session_id:
            raise ValueError("Cron Trigger 不属于当前 Session。")
        self._run_prompt(trigger.prompt)
