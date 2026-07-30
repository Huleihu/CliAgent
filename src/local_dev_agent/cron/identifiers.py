"""Cron 任务标识的本地基础设施适配器。"""

from uuid import uuid4


class UuidCronTaskIdGenerator:
    """使用 UUID4 生成跨进程碰撞概率极低且不含路径分隔符的标识。"""

    def new_task_id(self) -> str:
        """生成候选标识，最终重复检查仍由应用服务和仓储负责。"""

        return f"cron_{uuid4().hex}"
