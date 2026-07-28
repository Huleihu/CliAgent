"""S09 长期记忆持久化的稳定端口。"""

from typing import Protocol

from .schema import MemoryCatalog, MemoryEntry


class MemoryRepository(Protocol):
    """保存并读取工作区级长期记忆，不涉及模型选择或运行时策略。"""

    def list_entries(self) -> MemoryCatalog:
        """读取当前完整目录；缺失目录时返回空目录。"""

    def get(self, memory_id: str) -> MemoryEntry | None:
        """按精确标识读取一条记忆；不存在时返回空值。"""

    def save(self, entry: MemoryEntry) -> MemoryEntry:
        """原子替换单条记忆，并同步重建长期记忆索引。"""
