"""长期记忆文件仓储的单元测试。"""

from pathlib import Path

import pytest

from local_dev_agent.memory import (
    CorruptedMemoryFileError,
    FileSystemMemoryRepository,
    MemoryEntry,
    MemoryType,
)


def _entry(memory_id: str, description: str) -> MemoryEntry:
    return MemoryEntry(
        memory_id=memory_id,
        memory_type=MemoryType.USER,
        description=description,
        content=f"{description} 的完整长期说明。",
    )


def test_repository_returns_empty_catalog_before_first_write(tmp_path: Path) -> None:
    repository = FileSystemMemoryRepository(tmp_path / "memory")

    assert repository.list_entries().entries == ()
    assert repository.get("user-tabs") is None


def test_repository_persists_entry_and_rebuilds_sorted_index(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    repository = FileSystemMemoryRepository(root)
    repository.save(_entry("user-tabs", "使用 tab 缩进"))
    repository.save(_entry("feedback-no-mocks", "不要 mock 数据库"))

    restored = FileSystemMemoryRepository(root)
    assert tuple(entry.memory_id for entry in restored.list_entries().entries) == (
        "feedback-no-mocks",
        "user-tabs",
    )
    assert restored.get("user-tabs") == _entry("user-tabs", "使用 tab 缩进")
    assert (root / "MEMORY.md").read_text(encoding="utf-8") == (
        "- [feedback-no-mocks](feedback-no-mocks.md) — 不要 mock 数据库\n"
        "- [user-tabs](user-tabs.md) — 使用 tab 缩进\n"
    )


def test_repository_overwrites_same_memory_without_duplicate_index_line(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    repository = FileSystemMemoryRepository(root)
    repository.save(_entry("user-tabs", "使用 tab 缩进"))
    repository.save(_entry("user-tabs", "始终使用 tab 缩进"))

    assert len(repository.list_entries().entries) == 1
    assert (root / "MEMORY.md").read_text(encoding="utf-8").count("user-tabs") == 2


@pytest.mark.parametrize(
    "filename, content",
    (
        ("broken.md", "不是 frontmatter"),
        (
            "wrong-name.md",
            "---\nname: user-tabs\ndescription: 描述\ntype: user\n---\n\n正文\n",
        ),
    ),
)
def test_repository_rejects_corrupted_memory_file(
    tmp_path: Path,
    filename: str,
    content: str,
) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    (root / filename).write_text(content, encoding="utf-8")

    with pytest.raises(CorruptedMemoryFileError):
        FileSystemMemoryRepository(root).list_entries()


def test_repository_rejects_non_utf8_memory_file(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    (root / "user-tabs.md").write_bytes(b"\xff\xfe")

    with pytest.raises(CorruptedMemoryFileError):
        FileSystemMemoryRepository(root).list_entries()
