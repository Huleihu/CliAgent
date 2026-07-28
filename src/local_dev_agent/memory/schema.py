"""S09 跨会话长期记忆的不可变领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


_MEMORY_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _require_nonempty_text(field_name: str, value: str) -> str:
    """收束展示和持久化文本，避免空白字段进入长期索引。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


class MemoryType(StrEnum):
    """长期记忆的稳定用途分类。"""

    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """一条可跨会话复用的长期知识，不等同于对话或历史摘要。"""

    memory_id: str
    memory_type: MemoryType
    description: str
    content: str

    def __post_init__(self) -> None:
        """限定受控文件名和索引展示字段，阻止记忆层退化为任意文件读写。"""

        memory_id = _require_nonempty_text("memory_id", self.memory_id)
        if not _MEMORY_ID_PATTERN.fullmatch(memory_id):
            raise ValueError(
                "字段“memory_id”必须是仅含小写字母、数字和连字符的标识。"
            )
        if not isinstance(self.memory_type, MemoryType):
            raise ValueError("字段“memory_type”必须是 MemoryType 枚举值。")
        description = _require_nonempty_text("description", self.description)
        content = _require_nonempty_text("content", self.content)
        object.__setattr__(self, "memory_id", memory_id)
        object.__setattr__(self, "description", " ".join(description.split()))
        object.__setattr__(self, "content", content)


@dataclass(frozen=True, slots=True)
class MemoryCatalog:
    """某个工作区内全部长期记忆的稳定、按标识排序快照。"""

    entries: tuple[MemoryEntry, ...] = ()

    def __post_init__(self) -> None:
        """拒绝不稳定顺序和重复标识，使索引可复现且查询无歧义。"""

        if not isinstance(self.entries, tuple) or not all(
            isinstance(entry, MemoryEntry) for entry in self.entries
        ):
            raise ValueError("长期记忆目录必须是 MemoryEntry 元组。")
        memory_ids = tuple(entry.memory_id for entry in self.entries)
        if memory_ids != tuple(sorted(memory_ids)):
            raise ValueError("长期记忆目录必须按 memory_id 升序排列。")
        if len(set(memory_ids)) != len(memory_ids):
            raise ValueError("长期记忆目录不能包含重复 memory_id。")

    def get(self, memory_id: str) -> MemoryEntry | None:
        """按精确受控标识查询，绝不将查询值解释为磁盘路径。"""

        normalized_memory_id = _require_nonempty_text("memory_id", memory_id)
        return next(
            (
                entry
                for entry in self.entries
                if entry.memory_id == normalized_memory_id
            ),
            None,
        )
