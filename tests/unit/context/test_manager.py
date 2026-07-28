from pathlib import Path

import pytest

from local_dev_agent.context import (
    ContextBudget,
    ContextBudgetExceededError,
    ContextInputSnapshot,
    ContextManager,
    FileSystemToolResultArtifactStore,
    FullHistorySummaryCheckpointRebuilder,
    HistorySummaryCompactor,
    HistorySummaryCheckpoint,
    HistorySummaryCheckpointService,
    ToolResultBudgetCompactor,
    calculate_history_source_checksum,
)
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock, ToolResultBlock


class RecordingSummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.snapshots: list[ContextInputSnapshot] = []

    def summarize(self, snapshot: ContextInputSnapshot) -> str:
        self.snapshots.append(snapshot)
        return self._summary


class InMemoryCheckpointRepository:
    def __init__(self, checkpoint: HistorySummaryCheckpoint | None = None) -> None:
        self._checkpoint = checkpoint
        self.saved_checkpoints: list[HistorySummaryCheckpoint] = []

    def load(self, session_id: str) -> HistorySummaryCheckpoint | None:
        return self._checkpoint

    def save(self, checkpoint: HistorySummaryCheckpoint) -> None:
        self._checkpoint = checkpoint
        self.saved_checkpoints.append(checkpoint)


class RecordingEnricher:
    def __init__(self) -> None:
        self.snapshots: list[ContextInputSnapshot] = []

    def enrich(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        self.snapshots.append(snapshot)
        return ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=snapshot.messages,
            tools=snapshot.tools,
            system_prompt="派生记忆提示。",
        )


def _snapshot_with_large_result() -> ContextInputSnapshot:
    return ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("检查日志。"),),
            ),
            ModelMessage(
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(
                        tool_use_id="toolu-1",
                        content={"content": "甲" * 1_000},
                    ),
                ),
            ),
        ),
    )


def _manager(
    tmp_path: Path,
    *,
    budget: ContextBudget,
    summarizer: RecordingSummarizer,
    max_total_bytes: int = 100,
) -> ContextManager:
    return ContextManager(
        budget,
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts"),
            max_total_bytes=max_total_bytes,
            minimum_artifact_bytes=20,
            preview_max_characters=20,
        ),
        HistorySummaryCompactor(summarizer),
    )


def test_context_manager_propagates_artifacts_into_the_prepared_package(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_with_large_result()
    summarizer = RecordingSummarizer("不会使用。")
    manager = _manager(
        tmp_path,
        budget=ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        summarizer=summarizer,
    )

    package = manager.prepare(snapshot)

    assert len(package.artifacts) == 1
    assert not package.history_compacted
    assert not package.budget_report.exceeds_budget
    assert "artifact_ref" in package.snapshot.messages[-1].content[0].content  # type: ignore[union-attr]
    assert snapshot.messages[-1].content[0].content == {"content": "甲" * 1_000}  # type: ignore[union-attr]
    assert summarizer.snapshots == []


def test_context_manager_summarizes_only_when_preprocessors_leave_an_over_budget_snapshot(
    tmp_path: Path,
) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("甲" * 500),),
            ),
        ),
    )
    summarizer = RecordingSummarizer("当前目标：继续检查。")
    manager = _manager(
        tmp_path,
        budget=ContextBudget(
            context_window_tokens=200,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        summarizer=summarizer,
        max_total_bytes=10_000,
    )

    package = manager.prepare(snapshot)

    assert package.history_compacted
    assert summarizer.snapshots == [snapshot]
    assert package.snapshot.messages[0].content == (
        TextBlock("[已压缩的历史摘要]\n\n当前目标：继续检查。"),
    )
    assert not package.budget_report.exceeds_budget
    assert snapshot.messages[0].content == (TextBlock("甲" * 500),)


def test_context_manager_can_force_history_compaction_within_budget(tmp_path: Path) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("检查当前状态。"),),
            ),
        ),
    )
    summarizer = RecordingSummarizer("当前目标：继续检查。")
    manager = _manager(
        tmp_path,
        budget=ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        summarizer=summarizer,
        max_total_bytes=10_000,
    )

    package = manager.prepare(snapshot, force_history_compaction=True)

    assert package.history_compacted
    assert summarizer.snapshots == [snapshot]
    assert package.snapshot.messages[0].content == (
        TextBlock("[已压缩的历史摘要]\n\n当前目标：继续检查。"),
    )
    assert snapshot.messages[0].content == (TextBlock("检查当前状态。"),)


def test_context_manager_rejects_a_summary_that_still_exceeds_budget(tmp_path: Path) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("甲" * 500),),
            ),
        ),
    )
    manager = _manager(
        tmp_path,
        budget=ContextBudget(
            context_window_tokens=200,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        summarizer=RecordingSummarizer("乙" * 500),
        max_total_bytes=10_000,
    )

    with pytest.raises(ContextBudgetExceededError, match="历史摘要后上下文仍超过输入预算"):
        manager.prepare(snapshot)


def test_context_manager_reuses_a_valid_checkpoint_before_preprocessors(tmp_path: Path) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("较早历史。"),)),
            ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("较早回复。"),)),
            ModelMessage(role=MessageRole.USER, content=(TextBlock("最新问题。"),)),
        ),
    )
    checkpoint = HistorySummaryCheckpoint(
        session_id=snapshot.session_id,
        covered_message_count=2,
        source_checksum=calculate_history_source_checksum(
            session_id=snapshot.session_id,
            messages=snapshot.messages[:2],
        ),
        summary="已完成较早工作。",
    )
    repository = InMemoryCheckpointRepository(checkpoint)
    checkpoint_summarizer = RecordingSummarizer("不会重建。")
    fallback_summarizer = RecordingSummarizer("不会调用。")
    manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(fallback_summarizer),
        history_summary_checkpoint_service=HistorySummaryCheckpointService(
            repository,
            FullHistorySummaryCheckpointRebuilder(checkpoint_summarizer),
        ),
    )

    package = manager.prepare(snapshot)

    assert package.history_compacted
    assert package.snapshot.messages[0].content == (
        TextBlock("[历史摘要检查点]\n\n已完成较早工作。"),
    )
    assert package.snapshot.messages[1:] == snapshot.messages[2:]
    assert checkpoint_summarizer.snapshots == []
    assert fallback_summarizer.snapshots == []


def test_context_manager_enriches_only_the_restored_checkpoint_view(tmp_path: Path) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("较早历史。"),)),
            ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("较早回复。"),)),
            ModelMessage(role=MessageRole.USER, content=(TextBlock("最新问题。"),)),
        ),
    )
    checkpoint = HistorySummaryCheckpoint(
        session_id=snapshot.session_id,
        covered_message_count=2,
        source_checksum=calculate_history_source_checksum(
            session_id=snapshot.session_id,
            messages=snapshot.messages[:2],
        ),
        summary="已完成较早工作。",
    )
    enricher = RecordingEnricher()
    manager = ContextManager(
        ContextBudget(10_000, 1, 1),
        ToolResultBudgetCompactor(FileSystemToolResultArtifactStore(tmp_path / "artifacts")),
        HistorySummaryCompactor(RecordingSummarizer("不会调用。")),
        history_summary_checkpoint_service=HistorySummaryCheckpointService(
            InMemoryCheckpointRepository(checkpoint),
            FullHistorySummaryCheckpointRebuilder(RecordingSummarizer("不会重建。")),
        ),
    )

    package = manager.prepare(snapshot, context_enricher=enricher)

    assert enricher.snapshots[0].messages[0].content == (
        TextBlock("[历史摘要检查点]\n\n已完成较早工作。"),
    )
    assert enricher.snapshots[0].messages != snapshot.messages
    assert package.snapshot.system_prompt == "派生记忆提示。"
    assert snapshot.system_prompt is None


def test_context_manager_rebuilds_a_checkpoint_from_raw_history_after_forced_compaction(
    tmp_path: Path,
) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("第一条。"),)),
            ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("第二条。"),)),
            ModelMessage(role=MessageRole.USER, content=(TextBlock("第三条。"),)),
        ),
    )
    repository = InMemoryCheckpointRepository()
    checkpoint_summarizer = RecordingSummarizer("由完整历史重建。")
    fallback_summarizer = RecordingSummarizer("不会调用。")
    manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(fallback_summarizer),
        history_summary_checkpoint_service=HistorySummaryCheckpointService(
            repository,
            FullHistorySummaryCheckpointRebuilder(checkpoint_summarizer),
        ),
        checkpoint_tail_message_count=1,
    )

    package = manager.prepare(snapshot, force_history_compaction=True)

    assert checkpoint_summarizer.snapshots == [
        ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=snapshot.messages[:2],
        )
    ]
    assert repository.saved_checkpoints[0].covered_message_count == 2
    assert package.history_compacted
    assert package.snapshot.messages[0].content == (
        TextBlock("[历史摘要检查点]\n\n由完整历史重建。"),
    )
    assert package.snapshot.messages[1:] == snapshot.messages[2:]
    assert fallback_summarizer.snapshots == []


def test_context_manager_summarizes_all_of_a_short_history_when_forced(
    tmp_path: Path,
) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("第一条。"),)),
            ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("第二条。"),)),
            ModelMessage(role=MessageRole.USER, content=(TextBlock("第三条。"),)),
        ),
    )
    repository = InMemoryCheckpointRepository()
    checkpoint_summarizer = RecordingSummarizer("完整短历史摘要。")
    manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(RecordingSummarizer("不会调用。")),
        history_summary_checkpoint_service=HistorySummaryCheckpointService(
            repository,
            FullHistorySummaryCheckpointRebuilder(checkpoint_summarizer),
        ),
        checkpoint_tail_message_count=10,
    )

    package = manager.prepare(snapshot, force_history_compaction=True)

    assert checkpoint_summarizer.snapshots[0].messages == snapshot.messages
    assert repository.saved_checkpoints[0].covered_message_count == len(snapshot.messages)
    assert package.snapshot.messages == (
        ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock("[历史摘要检查点]\n\n完整短历史摘要。"),),
        ),
    )
