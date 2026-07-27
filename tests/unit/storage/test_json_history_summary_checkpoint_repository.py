import json
from pathlib import Path

import pytest

from local_dev_agent.context import (
    HistorySummaryCheckpoint,
    calculate_history_source_checksum,
)
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock
from local_dev_agent.storage import JsonFileHistorySummaryCheckpointRepository
from local_dev_agent.storage.errors import CorruptedHistorySummaryCheckpointFileError


def _checkpoint(*, session_id: str = "session-1", summary: str = "当前目标：继续开发。") -> HistorySummaryCheckpoint:
    messages = (
        ModelMessage(role=MessageRole.USER, content=(TextBlock("检查当前状态。"),)),
    )
    return HistorySummaryCheckpoint(
        session_id=session_id,
        covered_message_count=1,
        source_checksum=calculate_history_source_checksum(
            session_id=session_id,
            messages=messages,
        ),
        summary=summary,
    )


def test_checkpoint_repository_persists_a_checkpoint_across_instances(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    first_repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")

    first_repository.save(checkpoint)

    restored = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state").load(
        checkpoint.session_id
    )
    path = tmp_path / "state" / "history-summary-checkpoints" / "session-1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert restored == checkpoint
    assert payload == {
        "schema_version": 1,
        "entity_type": "history_summary_checkpoint",
        "session_id": "session-1",
        "covered_message_count": 1,
        "source_checksum": checkpoint.source_checksum,
        "summary": "当前目标：继续开发。",
    }


def test_checkpoint_repository_returns_none_for_a_missing_session(tmp_path: Path) -> None:
    repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")

    assert repository.load("missing-session") is None


def test_checkpoint_repository_replaces_only_the_same_session_checkpoint(tmp_path: Path) -> None:
    repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")
    first = _checkpoint(summary="旧摘要。")
    replacement = _checkpoint(summary="新摘要。")
    other_session = _checkpoint(session_id="session-2")

    repository.save(first)
    repository.save(other_session)
    repository.save(replacement)

    assert repository.load("session-1") == replacement
    assert repository.load("session-2") == other_session


@pytest.mark.parametrize(
    "payload",
    [
        "不是 JSON",
        json.dumps([]),
        json.dumps(
            {
                "schema_version": 2,
                "entity_type": "history_summary_checkpoint",
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "entity_type": "history_summary_checkpoint",
                "session_id": "session-1",
                "covered_message_count": True,
                "source_checksum": "sha256:" + "a" * 64,
                "summary": "摘要。",
            }
        ),
    ],
)
def test_checkpoint_repository_rejects_a_corrupted_or_unsupported_file(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "state" / "history-summary-checkpoints" / "session-1.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")

    with pytest.raises(CorruptedHistorySummaryCheckpointFileError, match="历史摘要检查点文件"):
        repository.load("session-1")


def test_checkpoint_repository_rejects_a_file_with_a_different_session_id(tmp_path: Path) -> None:
    repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")
    repository.save(_checkpoint(session_id="session-2"))
    source = tmp_path / "state" / "history-summary-checkpoints" / "session-2.json"
    target = tmp_path / "state" / "history-summary-checkpoints" / "session-1.json"
    source.replace(target)

    with pytest.raises(CorruptedHistorySummaryCheckpointFileError, match="历史摘要检查点文件"):
        repository.load("session-1")


def test_checkpoint_repository_preserves_the_previous_file_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")
    original = _checkpoint(summary="旧摘要。")
    repository.save(original)

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("替换失败。")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="替换失败"):
        repository.save(_checkpoint(summary="新摘要。"))

    assert repository.load("session-1") == original
    temporary_files = list(
        (tmp_path / "state" / "history-summary-checkpoints").glob("*.tmp")
    )
    assert temporary_files == []


@pytest.mark.parametrize("session_id", ["../outside", "nested/session", ""])
def test_checkpoint_repository_rejects_session_identifiers_that_escape_the_storage_directory(
    tmp_path: Path,
    session_id: str,
) -> None:
    repository = JsonFileHistorySummaryCheckpointRepository(tmp_path / "state")

    with pytest.raises(ValueError, match="会话标识不能包含路径分隔符"):
        repository.load(session_id)
