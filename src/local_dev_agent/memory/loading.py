"""长期记忆的目录格式化、选择结果校验与有界加载。"""

from __future__ import annotations

from dataclasses import dataclass

from .ports import MemoryRepository
from .schema import MemoryCatalog, MemoryEntry
from .selection import MemorySelectionRequest, MemorySelector


def _require_positive_integer(field_name: str, value: int) -> int:
    """统一校验加载预算，避免布尔值或负数绕过上下文边界。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"字段“{field_name}”必须是正整数。")
    return value


@dataclass(frozen=True, slots=True)
class MemoryLoadBudget:
    """一次运行最多选择和注入多少长期记忆的明确边界。"""

    max_items: int = 5
    max_entry_characters: int = 4_096
    max_total_characters: int = 16_384

    def __post_init__(self) -> None:
        """限制模型选择数量和正文体积，防止长期记忆挤占当前任务上下文。"""

        _require_positive_integer("max_items", self.max_items)
        max_entry_characters = _require_positive_integer(
            "max_entry_characters",
            self.max_entry_characters,
        )
        max_total_characters = _require_positive_integer(
            "max_total_characters",
            self.max_total_characters,
        )
        if max_total_characters < max_entry_characters:
            raise ValueError("字段“max_total_characters”不能小于单条记忆预算。")


@dataclass(frozen=True, slots=True)
class MemoryLoadResult:
    """一次选择后的稳定记忆视图，供后续 Runtime 在派生请求中注入。"""

    catalog: MemoryCatalog
    selected_entries: tuple[MemoryEntry, ...]
    omitted_memory_ids: tuple[str, ...]
    catalog_text: str
    relevant_memories_text: str

    def __post_init__(self) -> None:
        """固定加载结果，明确区分目录、实际正文与因预算忽略的候选项。"""

        if not isinstance(self.catalog, MemoryCatalog):
            raise ValueError("字段“catalog”必须是 MemoryCatalog 对象。")
        if not isinstance(self.selected_entries, tuple) or not all(
            isinstance(entry, MemoryEntry) for entry in self.selected_entries
        ):
            raise ValueError("字段“selected_entries”必须是 MemoryEntry 元组。")
        if not isinstance(self.omitted_memory_ids, tuple) or not all(
            isinstance(memory_id, str) and memory_id
            for memory_id in self.omitted_memory_ids
        ):
            raise ValueError("字段“omitted_memory_ids”必须是非空字符串元组。")
        if not isinstance(self.catalog_text, str) or not isinstance(
            self.relevant_memories_text,
            str,
        ):
            raise ValueError("记忆加载文本必须是字符串。")


def format_memory_catalog(catalog: MemoryCatalog) -> str:
    """只格式化名称与描述，确保完整正文不会常驻未来系统提示。"""

    if not isinstance(catalog, MemoryCatalog):
        raise TypeError("catalog 必须是 MemoryCatalog 对象。")
    return "".join(
        f"- [{entry.memory_id}]({entry.memory_id}.md) — {entry.description}\n"
        for entry in catalog.entries
    )


class MemoryLoader:
    """从仓储快照中选择并组装受预算约束的相关记忆正文。"""

    def __init__(
        self,
        repository: MemoryRepository,
        selector: MemorySelector,
        *,
        budget: MemoryLoadBudget | None = None,
    ) -> None:
        if not hasattr(repository, "list_entries"):
            raise ValueError("repository 必须提供 list_entries 方法。")
        if not hasattr(selector, "select"):
            raise ValueError("selector 必须提供 select 方法。")
        self._repository = repository
        self._selector = selector
        self._budget = budget or MemoryLoadBudget()

    def load(self, *, session_id: str, run_id: str, query: str) -> MemoryLoadResult:
        """基于一次目录快照选择记忆，忽略越界、重复或超预算的候选项。"""

        catalog = self._repository.list_entries()
        request = MemorySelectionRequest(
            session_id=session_id,
            run_id=run_id,
            query=query,
            catalog=catalog,
            max_items=self._budget.max_items,
        )
        selected_ids = self._selector.select(request)
        selected_entries, omitted_memory_ids = self._load_selected_entries(
            catalog,
            selected_ids,
        )
        return MemoryLoadResult(
            catalog=catalog,
            selected_entries=selected_entries,
            omitted_memory_ids=omitted_memory_ids,
            catalog_text=format_memory_catalog(catalog),
            relevant_memories_text=self._format_relevant_memories(selected_entries),
        )

    def _load_selected_entries(
        self,
        catalog: MemoryCatalog,
        selected_ids: tuple[str, ...],
    ) -> tuple[tuple[MemoryEntry, ...], tuple[str, ...]]:
        selected_entries: list[MemoryEntry] = []
        omitted_memory_ids: list[str] = []
        total_characters = 0
        seen_ids: set[str] = set()
        for memory_id in selected_ids:
            if not isinstance(memory_id, str) or memory_id in seen_ids:
                continue
            seen_ids.add(memory_id)
            try:
                entry = catalog.get(memory_id)
            except ValueError:
                continue
            if entry is None:
                continue
            segment = self._format_entry(entry)
            if (
                len(entry.content) > self._budget.max_entry_characters
                or total_characters + len(segment) > self._budget.max_total_characters
            ):
                omitted_memory_ids.append(memory_id)
                continue
            selected_entries.append(entry)
            total_characters += len(segment)
        return tuple(selected_entries), tuple(omitted_memory_ids)

    @staticmethod
    def _format_entry(entry: MemoryEntry) -> str:
        return f"## {entry.memory_id}\n{entry.content}"

    @classmethod
    def _format_relevant_memories(cls, entries: tuple[MemoryEntry, ...]) -> str:
        if not entries:
            return ""
        return "<relevant_memories>\n\n" + "\n\n".join(
            cls._format_entry(entry) for entry in entries
        ) + "\n\n</relevant_memories>"
