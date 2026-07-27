import hashlib
import json
from pathlib import Path

import pytest

from local_dev_agent.context import (
    ContextInputSnapshot,
    FileSystemToolResultArtifactStore,
    ToolResultBudgetCompactor,
)
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock, ToolResultBlock


def _snapshot_with_last_message(*blocks: ToolResultBlock) -> ContextInputSnapshot:
    return ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("检查文件。"),),
            ),
            ModelMessage(role=MessageRole.USER, content=blocks),
        ),
    )


def _result(tool_use_id: str, content: str) -> ToolResultBlock:
    return ToolResultBlock(tool_use_id=tool_use_id, content={"content": content})


def test_artifact_store_persists_full_json_content_with_stable_reference(
    tmp_path: Path,
) -> None:
    store = FileSystemToolResultArtifactStore(tmp_path)

    artifact = store.persist(
        tool_use_id="toolu-1",
        content={"content": "完整结果", "count": 2},
        is_error=False,
    )

    path = tmp_path / artifact.relative_path
    payload_bytes = path.read_bytes()
    payload = json.loads(payload_bytes)
    assert artifact.content_sha256 == hashlib.sha256(payload_bytes).hexdigest()
    assert artifact.content_bytes == len(
        json.dumps(
            {"content": "完整结果", "count": 2},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert payload == {
        "schema_version": 1,
        "tool_use_id": "toolu-1",
        "is_error": False,
        "content": {"content": "完整结果", "count": 2},
    }


def test_artifact_store_reuses_an_existing_content_addressed_file(tmp_path: Path) -> None:
    store = FileSystemToolResultArtifactStore(tmp_path)

    first = store.persist(
        tool_use_id="toolu-1",
        content={"content": "完整结果"},
        is_error=False,
    )
    second = store.persist(
        tool_use_id="toolu-1",
        content={"content": "完整结果"},
        is_error=False,
    )

    assert first == second
    assert len(tuple((tmp_path / "tool-results").glob("*.json"))) == 1


def test_compactor_keeps_original_snapshot_when_last_message_is_not_tool_result(
    tmp_path: Path,
) -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("普通用户输入。"),),
            ),
        ),
    )
    compactor = ToolResultBudgetCompactor(
        FileSystemToolResultArtifactStore(tmp_path),
        max_total_bytes=10,
        minimum_artifact_bytes=5,
    )

    result = compactor.compact(snapshot)

    assert result.snapshot is snapshot
    assert not result.compacted
    assert result.artifacts == ()
    assert result.original_total_bytes == 0


def test_compactor_preserves_small_results_without_writing_artifacts(tmp_path: Path) -> None:
    snapshot = _snapshot_with_last_message(_result("toolu-1", "很短"))
    compactor = ToolResultBudgetCompactor(
        FileSystemToolResultArtifactStore(tmp_path),
        max_total_bytes=10_000,
        minimum_artifact_bytes=10,
    )

    result = compactor.compact(snapshot)

    assert result.snapshot is snapshot
    assert not result.compacted
    assert not (tmp_path / "tool-results").exists()


def test_compactor_replaces_large_result_only_in_derived_snapshot(tmp_path: Path) -> None:
    original_block = _result("toolu-1", "甲" * 100)
    snapshot = _snapshot_with_last_message(original_block)
    compactor = ToolResultBudgetCompactor(
        FileSystemToolResultArtifactStore(tmp_path),
        max_total_bytes=100,
        minimum_artifact_bytes=50,
        preview_max_characters=20,
    )

    result = compactor.compact(snapshot)

    assert result.compacted
    assert result.snapshot is not snapshot
    assert result.original_total_bytes > result.remaining_total_bytes
    assert snapshot.messages[-1].content == (original_block,)
    compacted_block = result.snapshot.messages[-1].content[0]
    assert isinstance(compacted_block, ToolResultBlock)
    assert compacted_block.tool_use_id == "toolu-1"
    assert compacted_block.content["preview"] == '{"content":"甲甲甲甲甲甲甲甲'
    artifact_path = tmp_path / compacted_block.content["artifact_ref"]
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["content"] == {
        "content": "甲" * 100
    }


def test_compactor_reduces_the_preview_until_the_reference_is_smaller(
    tmp_path: Path,
) -> None:
    original_block = _result("toolu-1", "甲" * 1_000)
    snapshot = _snapshot_with_last_message(original_block)
    compactor = ToolResultBudgetCompactor(
        FileSystemToolResultArtifactStore(tmp_path),
        max_total_bytes=100,
        minimum_artifact_bytes=20,
    )

    result = compactor.compact(snapshot)

    compacted_block = result.snapshot.messages[-1].content[0]
    assert isinstance(compacted_block, ToolResultBlock)
    assert len(compacted_block.content["preview"]) < len('{"content":"甲"' + "甲" * 1_000)
    assert result.remaining_total_bytes < result.original_total_bytes


def test_compactor_persists_largest_results_first_until_within_budget(
    tmp_path: Path,
) -> None:
    small = _result("toolu-small", "a" * 20)
    medium = _result("toolu-medium", "b" * 3_000)
    large = _result("toolu-large", "c" * 5_000)
    snapshot = _snapshot_with_last_message(small, medium, large)
    compactor = ToolResultBudgetCompactor(
        FileSystemToolResultArtifactStore(tmp_path),
        max_total_bytes=1_000,
        minimum_artifact_bytes=500,
        preview_max_characters=10,
    )

    result = compactor.compact(snapshot)

    assert result.remaining_total_bytes <= 1_000
    assert tuple(artifact.relative_path for artifact in result.artifacts)
    assert len(result.artifacts) == 2
    compacted_contents = result.snapshot.messages[-1].content
    assert isinstance(compacted_contents[0], ToolResultBlock)
    assert compacted_contents[0].content == small.content
    assert "artifact_ref" in compacted_contents[1].content
    assert "artifact_ref" in compacted_contents[2].content


def test_compactor_keeps_budget_excess_when_no_result_is_large_enough(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_with_last_message(
        _result("toolu-1", "a" * 20),
        _result("toolu-2", "b" * 20),
    )
    compactor = ToolResultBudgetCompactor(
        FileSystemToolResultArtifactStore(tmp_path),
        max_total_bytes=60,
        minimum_artifact_bytes=60,
    )

    result = compactor.compact(snapshot)

    assert not result.compacted
    assert result.remaining_total_bytes > 60
    assert result.snapshot is snapshot


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"max_total_bytes": 0}, "字段“max_total_bytes”必须是正整数"),
        (
            {"max_total_bytes": 10, "minimum_artifact_bytes": 11},
            "minimum_artifact_bytes 不能大于 max_total_bytes",
        ),
        (
            {"preview_max_characters": False},
            "字段“preview_max_characters”必须是正整数",
        ),
    ],
)
def test_compactor_rejects_invalid_configuration(
    tmp_path: Path,
    arguments: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ToolResultBudgetCompactor(FileSystemToolResultArtifactStore(tmp_path), **arguments)
