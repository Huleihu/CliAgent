"""待办清单持久化的稳定端口。"""

from typing import Protocol

from .schema import TodoSnapshot


class TodoRepository(Protocol):
    """保存并读取平铺待办清单，不包含工具或运行时策略。"""

    def load(self, todo_list_id: str) -> TodoSnapshot:
        """读取指定清单；尚未保存时返回空快照。"""

    def replace(self, snapshot: TodoSnapshot) -> TodoSnapshot:
        """以完整快照原子替换指定清单。"""
