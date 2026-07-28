"""长期记忆领域模型的契约测试。"""

import pytest

from local_dev_agent.memory import MemoryCatalog, MemoryEntry, MemoryType


def test_memory_entry_normalizes_index_description() -> None:
    entry = MemoryEntry(
        memory_id="user-preference-tabs",
        memory_type=MemoryType.USER,
        description="  用户偏好\n使用 tab 缩进  ",
        content="始终使用 tab。",
    )

    assert entry.description == "用户偏好 使用 tab 缩进"


@pytest.mark.parametrize("memory_id", ("Uppercase", "has_space", "../escape", ""))
def test_memory_entry_rejects_unsafe_memory_id(memory_id: str) -> None:
    with pytest.raises(ValueError, match="memory_id"):
        MemoryEntry(
            memory_id=memory_id,
            memory_type=MemoryType.USER,
            description="描述",
            content="正文",
        )


def test_memory_catalog_rejects_unsorted_or_duplicate_entries() -> None:
    first = MemoryEntry("a-memory", MemoryType.USER, "A", "正文 A")
    second = MemoryEntry("b-memory", MemoryType.PROJECT, "B", "正文 B")

    with pytest.raises(ValueError, match="升序"):
        MemoryCatalog(entries=(second, first))
    with pytest.raises(ValueError, match="重复"):
        MemoryCatalog(entries=(first, first))
