"""Team 领域默认时钟适配器。"""

from datetime import datetime, timezone


class SystemTeamClock:
    """返回带时区 UTC 时间的系统时钟。"""

    def now(self) -> datetime:
        """为仓储和应用服务提供一致的持久时间语义。"""

        return datetime.now(timezone.utc)
