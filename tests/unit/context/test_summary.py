from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.context import ContextInputSnapshot, HistorySummaryCompactor
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock
from local_dev_agent.tools.schema import ToolDefinition


class FakeConversationSummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.snapshots: list[ContextInputSnapshot] = []

    def summarize(self, snapshot: ContextInputSnapshot) -> str:
        self.snapshots.append(snapshot)
        return self._summary


def _snapshot() -> ContextInputSnapshot:
    return ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        system_prompt="遵循项目规则。",
        tools=(
            ToolDefinition(
                name="read_file",
                description="读取文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("检查 README。"),),
            ),
            ModelMessage(
                role=MessageRole.ASSISTANT,
                content=(TextBlock("我会读取文件。"),),
            ),
        ),
    )


def test_history_summary_compactor_replaces_messages_with_a_summary() -> None:
    snapshot = _snapshot()
    summarizer = FakeConversationSummarizer("当前目标：检查 README；下一步：读取文件。")

    result = HistorySummaryCompactor(summarizer).compact(snapshot)

    assert summarizer.snapshots == [snapshot]
    assert result is not snapshot
    assert result.session_id == snapshot.session_id
    assert result.run_id == snapshot.run_id
    assert result.system_prompt == snapshot.system_prompt
    assert result.tools == snapshot.tools
    assert result.messages == (
        ModelMessage(
            role=MessageRole.USER,
            content=(
                TextBlock(
                    "[已压缩的历史摘要]\n\n当前目标：检查 README；下一步：读取文件。"
                ),
            ),
        ),
    )


def test_history_summary_compactor_does_not_mutate_the_source_snapshot() -> None:
    snapshot = _snapshot()
    original_messages = snapshot.messages

    result = HistorySummaryCompactor(FakeConversationSummarizer("继续执行。")).compact(
        snapshot
    )

    assert snapshot.messages == original_messages
    assert result.messages != snapshot.messages
    with pytest.raises(FrozenInstanceError):
        snapshot.messages = ()  # type: ignore[misc]


@pytest.mark.parametrize("summary", ["", "   "])
def test_history_summary_compactor_rejects_blank_summary(summary: str) -> None:
    with pytest.raises(ValueError, match="历史摘要必须是非空字符串"):
        HistorySummaryCompactor(FakeConversationSummarizer(summary)).compact(_snapshot())


def test_history_summary_compactor_propagates_summarizer_failures() -> None:
    class FailingSummarizer:
        def summarize(self, snapshot: ContextInputSnapshot) -> str:
            raise RuntimeError("摘要服务不可用。")

    with pytest.raises(RuntimeError, match="摘要服务不可用"):
        HistorySummaryCompactor(FailingSummarizer()).compact(_snapshot())


def test_history_summary_compactor_requires_a_summarizer_port() -> None:
    with pytest.raises(ValueError, match="summarizer 必须提供 summarize 方法"):
        HistorySummaryCompactor(object())  # type: ignore[arg-type]
