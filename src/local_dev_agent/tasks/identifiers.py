"""任务标识生成的本地实现。"""

from uuid import uuid4


class UuidTaskIdGenerator:
    """使用 UUID4 生成跨进程碰撞概率极低的任务标识。"""

    def new_task_id(self) -> str:
        """生成不携带路径分隔符的任务标识，交由仓储负责最终冲突检查。"""

        return f"task_{uuid4().hex}"
