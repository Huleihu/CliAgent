import pytest

from local_dev_agent.context import (
    ContextInputSnapshot,
    FullHistorySummaryCheckpointRebuilder,
    HistorySummaryCheckpoint,
    HistorySummaryCheckpointService,
    build_history_summary_checkpoint_messages,
    calculate_history_source_checksum,
)
from local_dev_agent.context.checkpoints import HistorySummaryCheckpointSourceMismatchError
from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


class InMemoryCheckpointRepository:
    def __init__(self, checkpoint: HistorySummaryCheckpoint | None = None) -> None:
        self._checkpoint = checkpoint
        self.loaded_session_ids: list[str] = []
        self.saved_checkpoints: list[HistorySummaryCheckpoint] = []

    def load(self, session_id: str) -> HistorySummaryCheckpoint | None:
        self.loaded_session_ids.append(session_id)
        return self._checkpoint

    def save(self, checkpoint: HistorySummaryCheckpoint) -> None:
        self._checkpoint = checkpoint
        self.saved_checkpoints.append(checkpoint)


class RecordingSummarizer:
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
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("检查项目状态。"),)),
            ModelMessage(
                role=MessageRole.ASSISTANT,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="read_file",
                        input={"path": "README.md"},
                    ),
                ),
            ),
            ModelMessage(
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(
                        tool_use_id="toolu-1",
                        content={"content": "项目说明"},
                    ),
                ),
            ),
            ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("已读取。"),)),
            ModelMessage(role=MessageRole.USER, content=(TextBlock("继续实现。"),)),
        ),
    )


def _checkpoint(snapshot: ContextInputSnapshot, *, covered_message_count: int = 3) -> HistorySummaryCheckpoint:
    return HistorySummaryCheckpoint(
        session_id=snapshot.session_id,
        covered_message_count=covered_message_count,
        source_checksum=calculate_history_source_checksum(
            session_id=snapshot.session_id,
            messages=snapshot.messages[:covered_message_count],
        ),
        summary="已检查项目并读取 README。",
    )


def test_checkpoint_service_restores_a_summary_with_the_original_uncovered_tail() -> None:
    snapshot = _snapshot()
    repository = InMemoryCheckpointRepository(_checkpoint(snapshot))
    service = HistorySummaryCheckpointService(
        repository,
        FullHistorySummaryCheckpointRebuilder(RecordingSummarizer("不会调用。")),
    )

    view = service.restore_view(snapshot)

    assert repository.loaded_session_ids == ["session-1"]
    assert view.session_id == snapshot.session_id
    assert view.run_id == snapshot.run_id
    assert view.system_prompt == snapshot.system_prompt
    assert view.messages[0] == ModelMessage(
        role=MessageRole.USER,
        content=(TextBlock("[历史摘要检查点]\n\n已检查项目并读取 README。"),),
    )
    assert view.messages[1:] == snapshot.messages[3:]
    assert snapshot.messages == _snapshot().messages


def test_checkpoint_message_builder_combines_only_the_summary_and_original_tail() -> None:
    snapshot = _snapshot()

    messages = build_history_summary_checkpoint_messages(
        session_id=snapshot.session_id,
        messages=snapshot.messages,
        checkpoint=_checkpoint(snapshot),
    )

    assert messages[0] == ModelMessage(
        role=MessageRole.USER,
        content=(TextBlock("[历史摘要检查点]\n\n已检查项目并读取 README。"),),
    )
    assert messages[1:] == snapshot.messages[3:]


def test_checkpoint_service_returns_the_complete_snapshot_when_no_checkpoint_exists() -> None:
    snapshot = _snapshot()
    service = HistorySummaryCheckpointService(
        InMemoryCheckpointRepository(),
        FullHistorySummaryCheckpointRebuilder(RecordingSummarizer("不会调用。")),
    )

    assert service.restore_view(snapshot) is snapshot


def test_checkpoint_service_rejects_a_checkpoint_with_a_changed_source() -> None:
    snapshot = _snapshot()
    checkpoint = _checkpoint(snapshot)
    changed_snapshot = ContextInputSnapshot(
        session_id=snapshot.session_id,
        run_id=snapshot.run_id,
        system_prompt=snapshot.system_prompt,
        messages=(
            *snapshot.messages[:2],
            ModelMessage(
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(
                        tool_use_id="toolu-1",
                        content={"content": "内容已改变"},
                    ),
                ),
            ),
            *snapshot.messages[3:],
        ),
    )
    service = HistorySummaryCheckpointService(
        InMemoryCheckpointRepository(checkpoint),
        FullHistorySummaryCheckpointRebuilder(RecordingSummarizer("不会调用。")),
    )

    with pytest.raises(HistorySummaryCheckpointSourceMismatchError, match="来源校验和不匹配"):
        service.restore_view(changed_snapshot)


def test_checkpoint_service_rebuilds_from_the_complete_original_history_and_saves_it() -> None:
    snapshot = _snapshot()
    repository = InMemoryCheckpointRepository()
    summarizer = RecordingSummarizer("从完整原始历史生成的摘要。")
    service = HistorySummaryCheckpointService(
        repository,
        FullHistorySummaryCheckpointRebuilder(summarizer),
    )

    view = service.rebuild_view_from_full_history(
        snapshot,
        desired_covered_message_count=3,
    )

    assert summarizer.snapshots == [
        ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            system_prompt=snapshot.system_prompt,
            messages=snapshot.messages[:3],
        )
    ]
    assert len(repository.saved_checkpoints) == 1
    checkpoint = repository.saved_checkpoints[0]
    assert checkpoint.covered_message_count == 3
    assert view.messages[0].content == (
        TextBlock("[历史摘要检查点]\n\n从完整原始历史生成的摘要。"),
    )
    assert view.messages[1:] == snapshot.messages[3:]


def test_rebuilder_moves_a_requested_boundary_before_a_tool_exchange() -> None:
    snapshot = _snapshot()
    summarizer = RecordingSummarizer("安全摘要。")
    rebuilder = FullHistorySummaryCheckpointRebuilder(summarizer)

    checkpoint = rebuilder.rebuild(snapshot, desired_covered_message_count=2)

    assert checkpoint.covered_message_count == 1
    assert summarizer.snapshots[0].messages == snapshot.messages[:1]


def test_checkpoint_service_requires_repository_and_rebuilder_ports() -> None:
    with pytest.raises(ValueError, match="repository 必须提供 load 和 save 方法"):
        HistorySummaryCheckpointService(object(), object())  # type: ignore[arg-type]

    class RepositoryOnly:
        def load(self, session_id: str) -> None:
            return None

        def save(self, checkpoint: HistorySummaryCheckpoint) -> None:
            return None

    with pytest.raises(ValueError, match="rebuilder 必须提供 rebuild 方法"):
        HistorySummaryCheckpointService(RepositoryOnly(), object())  # type: ignore[arg-type]
