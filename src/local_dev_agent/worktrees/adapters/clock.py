"""工作树审计事件使用的 UTC 时钟适配器。"""

from datetime import datetime, timezone


class UtcWorktreeClock:
    """向领域服务提供带 UTC 时区的当前时间。"""

    def now(self) -> datetime:
        """返回当前 UTC 时间，供 JSONL 事件稳定序列化。"""

        return datetime.now(timezone.utc)
