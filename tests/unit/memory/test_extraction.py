"""长期记忆提取与保存的单元测试。"""

from local_dev_agent.memory import (
    MemoryCatalog,
    MemoryEntry,
    MemoryExtractionService,
    MemoryType,
    ModelMemoryExtractor,
)
from local_dev_agent.models import FakeModel, MessageRole, ModelMessage, ModelResponse, TextBlock


class Repository:
    def __init__(self, entries=()) -> None:
        self.entries = list(entries)

    def list_entries(self) -> MemoryCatalog:
        return MemoryCatalog(entries=tuple(sorted(self.entries, key=lambda item: item.memory_id)))

    def save(self, entry: MemoryEntry) -> MemoryEntry:
        self.entries.append(entry)
        return entry


def test_extraction_service_saves_new_entries_and_skips_existing_ids() -> None:
    existing = MemoryEntry("user-tabs", MemoryType.USER, "使用 tab", "始终使用 tab。")
    model = FakeModel(
        ModelResponse.text_completion(
            '[{"name":"user-tabs","type":"user","description":"重复","content":"重复"},'
            '{"name":"feedback-no-mocks","type":"feedback","description":"不要 mock 数据库","content":"测试应使用真实数据库。"}]'
        )
    )
    repository = Repository((existing,))
    service = MemoryExtractionService(repository, ModelMemoryExtractor(model))

    saved = service.extract_and_save(
        session_id="session-1",
        run_id="run-1",
        messages=(ModelMessage(MessageRole.USER, (TextBlock("不要 mock 数据库。"),)),),
    )

    assert tuple(entry.memory_id for entry in saved) == ("feedback-no-mocks",)
    assert tuple(entry.memory_id for entry in repository.list_entries().entries) == (
        "feedback-no-mocks",
        "user-tabs",
    )
    assert model.requests[0].tools == ()
