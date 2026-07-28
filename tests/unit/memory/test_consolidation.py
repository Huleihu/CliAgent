"""长期记忆低频整理的单元测试。"""

from local_dev_agent.memory import MemoryCatalog, MemoryConsolidationPolicy, MemoryConsolidationService, MemoryEntry, MemoryType


class Repository:
    def __init__(self, catalog): self.catalog = catalog
    def list_entries(self): return self.catalog
    def replace_all(self, catalog): self.catalog = catalog; return catalog


class Consolidator:
    def __init__(self): self.calls = 0
    def consolidate(self, catalog, *, session_id, run_id):
        self.calls += 1
        return MemoryCatalog(entries=(catalog.entries[0],))


def test_consolidation_runs_only_at_threshold_and_replaces_catalog() -> None:
    entries = (
        MemoryEntry("project-auth", MemoryType.PROJECT, "认证", "认证事实。"),
        MemoryEntry("user-tabs", MemoryType.USER, "tab", "使用 tab。"),
    )
    repository = Repository(MemoryCatalog(entries=entries))
    consolidator = Consolidator()
    service = MemoryConsolidationService(repository, consolidator, MemoryConsolidationPolicy(2))

    assert service.consolidate_if_needed(session_id="session-1", run_id="run-1")
    assert consolidator.calls == 1
    assert tuple(entry.memory_id for entry in repository.catalog.entries) == ("project-auth",)
