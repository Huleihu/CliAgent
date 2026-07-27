from local_dev_agent.context import FileSystemToolResultArtifactStore
from local_dev_agent.tools import ToolCallRequest, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import ReadArtifactTool


def _tool_with_artifact(tmp_path):
    store = FileSystemToolResultArtifactStore(tmp_path / "artifacts")
    artifact = store.persist(
        tool_use_id="toolu-1",
        content={"content": "甲" * 100},
        is_error=False,
    )
    return ReadArtifactTool(store), artifact


def test_read_artifact_tool_returns_limited_pages_from_a_known_reference(tmp_path) -> None:
    tool, artifact = _tool_with_artifact(tmp_path)

    result = tool.run(
        {"artifact_ref": artifact.relative_path, "max_characters": 20}
    )

    assert result["artifact_ref"] == artifact.relative_path
    assert len(result["content"]) == 20
    assert result["offset"] == 0
    assert result["next_offset"] == 20
    assert result["truncated"] is True
    assert "root" not in result
    assert "path" not in result


def test_read_artifact_tool_reuses_structured_tool_failures_for_invalid_references(tmp_path) -> None:
    tool, _ = _tool_with_artifact(tmp_path)
    registry = ToolRegistry()
    registry.register(tool)

    result = ToolExecutor(registry).execute(
        ToolCallRequest(
            name="read_artifact",
            arguments={"artifact_ref": "../secret.txt"},
            call_id="toolu-1",
        )
    )

    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ToolExecutionError"


def test_read_artifact_tool_rejects_excessive_page_size(tmp_path) -> None:
    tool, artifact = _tool_with_artifact(tmp_path)
    registry = ToolRegistry()
    registry.register(tool)

    result = ToolExecutor(registry).execute(
        ToolCallRequest(
            name="read_artifact",
            arguments={"artifact_ref": artifact.relative_path, "max_characters": 12_001},
            call_id="toolu-1",
        )
    )

    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ToolValidationError"
