from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    ModelRequest,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def test_legacy_user_input_is_normalized_to_a_user_message() -> None:
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="检查项目状态。",
    )

    assert request.conversation == (
        ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock("检查项目状态。"),),
        ),
    )


def test_request_preserves_a_multi_turn_tool_conversation() -> None:
    messages = (
        ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock("读取 README。"),),
        ),
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
    )

    request = ModelRequest.from_messages(
        session_id="session-1",
        run_id="run-1",
        messages=messages,
    )

    assert request.user_input is None
    assert request.conversation == messages


def test_tool_result_freezes_its_top_level_content_snapshot() -> None:
    content = {"content": "初始结果"}
    result = ToolResultBlock(tool_use_id="toolu-1", content=content)
    content["content"] = "已修改"

    assert result.content["content"] == "初始结果"
    with pytest.raises(TypeError):
        result.content["content"] = "不能修改"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.is_error = True  # type: ignore[misc]


def test_model_message_rejects_blocks_for_the_wrong_role() -> None:
    with pytest.raises(ValueError, match="不允许的内容块"):
        ModelMessage(
            role=MessageRole.USER,
            content=(
                ToolUseBlock(
                    tool_use_id="toolu-1",
                    name="read_file",
                    input={"path": "README.md"},
                ),
            ),
        )

    with pytest.raises(ValueError, match="不允许的内容块"):
        ModelMessage(
            role=MessageRole.ASSISTANT,
            content=(ToolResultBlock(tool_use_id="toolu-1", content={}),),
        )


def test_model_request_rejects_mixed_or_missing_context_sources() -> None:
    message = ModelMessage(
        role=MessageRole.USER,
        content=(TextBlock("读取 README。"),),
    )

    with pytest.raises(ValueError, match="不能同时提供"):
        ModelRequest(
            session_id="session-1",
            run_id="run-1",
            user_input="读取 README。",
            messages=(message,),
        )

    with pytest.raises(ValueError, match="必须提供"):
        ModelRequest(session_id="session-1", run_id="run-1")
