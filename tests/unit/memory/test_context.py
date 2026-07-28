"""长期记忆派生请求视图的单元测试。"""

from local_dev_agent.context import ContextInputSnapshot
from local_dev_agent.memory import (
    MemoryCatalog,
    MemoryEntry,
    MemoryLoadResult,
    MemoryRequestContext,
    MemoryType,
    format_memory_catalog,
)
from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
)


def test_memory_request_context_injects_derived_view_without_mutating_source() -> None:
    entry = MemoryEntry(
        "project-auth",
        MemoryType.PROJECT,
        "认证重构由合规驱动",
        "保留审批和审计链路。",
    )
    catalog = MemoryCatalog(entries=(entry,))
    load_result = MemoryLoadResult(
        catalog=catalog,
        selected_entries=(entry,),
        omitted_memory_ids=(),
        catalog_text=format_memory_catalog(catalog),
        relevant_memories_text=(
            "<relevant_memories>\n\n## project-auth\n"
            "保留审批和审计链路。\n\n</relevant_memories>"
        ),
    )
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        system_prompt="基础系统提示。",
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("继续认证重构。"),)),
            ModelMessage(
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(tool_use_id="toolu-1", content={"ok": True}),
                ),
            ),
        ),
    )

    enriched = MemoryRequestContext(load_result).enrich(snapshot)

    assert "基础系统提示。" in enriched.system_prompt  # type: ignore[operator]
    assert "project-auth" in enriched.system_prompt  # type: ignore[operator]
    assert enriched.messages[0].content == (
        TextBlock(
            "<relevant_memories>\n\n## project-auth\n"
            "保留审批和审计链路。\n\n</relevant_memories>\n\n继续认证重构。"
        ),
    )
    assert enriched.messages[1] == snapshot.messages[1]
    assert snapshot.system_prompt == "基础系统提示。"
    assert snapshot.messages[0].content == (TextBlock("继续认证重构。"),)
