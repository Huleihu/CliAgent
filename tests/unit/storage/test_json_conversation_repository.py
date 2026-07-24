import json

import pytest

from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.storage.errors import CorruptedConversationFileError
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository


def test_conversation_repository_persists_messages_across_instances(tmp_path) -> None:
    messages = (
        ModelMessage(role=MessageRole.USER, content=(TextBlock("列出文件。"),)),
        ModelMessage(
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="toolu-1",
                    name="list_files",
                    input={},
                ),
            ),
        ),
        ModelMessage(
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="toolu-1",
                    content={"files": ["README.md"]},
                ),
            ),
        ),
        ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("找到 README。"),)),
    )
    repository = JsonFileConversationRepository(tmp_path)

    repository.append_messages("session-1", messages[:2])
    repository.append_messages("session-1", messages[2:])

    restored_repository = JsonFileConversationRepository(tmp_path)
    assert restored_repository.get_messages("session-1") == messages
    payload = json.loads((tmp_path / "conversations" / "session-1.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["entity_type"] == "conversation"


def test_conversation_repository_returns_empty_history_for_a_missing_session(tmp_path) -> None:
    assert JsonFileConversationRepository(tmp_path).get_messages("missing-session") == ()


def test_conversation_repository_reports_a_corrupted_file_in_chinese(tmp_path) -> None:
    path = tmp_path / "conversations" / "session-1.json"
    path.parent.mkdir()
    path.write_text("{不是有效 JSON", encoding="utf-8")

    with pytest.raises(CorruptedConversationFileError, match="会话消息文件.*已损坏"):
        JsonFileConversationRepository(tmp_path).get_messages("session-1")
