"""长期记忆目录格式化与有界加载的单元测试。"""

from local_dev_agent.memory import (
    MemoryCatalog,
    MemoryEntry,
    MemoryLoadBudget,
    MemoryLoader,
    MemoryType,
    format_memory_catalog,
)


class _Repository:
    def __init__(self, catalog: MemoryCatalog) -> None:
        self._catalog = catalog

    def list_entries(self) -> MemoryCatalog:
        return self._catalog


class _Selector:
    def __init__(self, selected_ids: tuple[str, ...]) -> None:
        self._selected_ids = selected_ids

    def select(self, request):
        return self._selected_ids


def _entry(memory_id: str, content: str) -> MemoryEntry:
    return MemoryEntry(memory_id, MemoryType.USER, f"{memory_id} 描述", content)


def test_format_memory_catalog_excludes_memory_body() -> None:
    catalog = MemoryCatalog(entries=(_entry("user-tabs", "不要出现在目录中。"),))

    assert format_memory_catalog(catalog) == "- [user-tabs](user-tabs.md) — user-tabs 描述\n"


def test_loader_uses_selection_order_and_formats_relevant_memory_boundary() -> None:
    first = _entry("project-auth", "认证重构由合规驱动。")
    second = _entry("user-tabs", "始终使用 tab。")
    catalog = MemoryCatalog(entries=(first, second))
    loader = MemoryLoader(_Repository(catalog), _Selector(("user-tabs", "project-auth")))

    result = loader.load(session_id="session-1", run_id="run-1", query="认证怎么改")

    assert result.selected_entries == (second, first)
    assert result.omitted_memory_ids == ()
    assert result.relevant_memories_text == (
        "<relevant_memories>\n\n"
        "## user-tabs\n始终使用 tab。\n\n"
        "## project-auth\n认证重构由合规驱动。\n\n"
        "</relevant_memories>"
    )


def test_loader_omits_oversized_and_total_budget_overflow_entries() -> None:
    oversized = _entry("large-memory", "x" * 11)
    first = _entry("project-auth", "12345")
    second = _entry("user-tabs", "67890")
    catalog = MemoryCatalog(entries=(oversized, first, second))
    loader = MemoryLoader(
        _Repository(catalog),
        _Selector(("../unsafe", "large-memory", "project-auth", "user-tabs")),
        budget=MemoryLoadBudget(
            max_items=3,
            max_entry_characters=10,
            max_total_characters=30,
        ),
    )

    result = loader.load(session_id="session-1", run_id="run-1", query="查询")

    assert result.selected_entries == (first,)
    assert result.omitted_memory_ids == ("large-memory", "user-tabs")
