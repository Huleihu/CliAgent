"""Cron 调度使用的本地时钟适配器。"""

from datetime import datetime


class SystemCronClock:
    """返回宿主机本地时区的带时区时间，符合 cron 的本地时间语义。"""

    def now(self) -> datetime:
        """读取当前本地时间；测试应改用 Fake Clock。"""

        return datetime.now().astimezone()
