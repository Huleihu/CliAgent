from pathlib import Path

import pytest

from local_dev_agent.context import (
    ContextBudget,
    ContextBudgetExceededError,
    ContextInputSnapshot,
    ContextManager,
    FileSystemToolResultArtifactStore,
    HistorySummaryCompactor,
    ToolResultBudgetCompactor,
)
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock, ToolResultBlock


class RecordingSummarizer:
    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.snapshots: list[ContextInputSnapshot] = []

    def summarize(self, snapshot: ContextInputSnapshot) -> str:
        self.snapshots.append(snapshot)
        return self._summary


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
