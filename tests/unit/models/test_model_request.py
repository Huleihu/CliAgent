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
from local_dev_agent.tools.schema import ToolDefinition


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


def test_model_request_preserves_tool_definitions_for_the_provider() -> None:
    tool = ToolDefinition(
        name="read_file",
        description="读取文本文件。",
        parameters={"type": "object", "properties": {}},
    )
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="读取 README。",
        tools=(tool,),
    )

    assert request.tools == (tool,)


def test_model_request_preserves_an_optional_system_prompt() -> None:
    request = ModelRequest.from_messages(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("检查项目状态。"),),
            ),
        ),
        system_prompt="优先维护待办清单。",
    )

    assert request.system_prompt == "优先维护待办清单。"


def test_model_request_preserves_an_optional_model_override() -> None:
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="检查项目状态。",
        model_id="fallback-model",
    )

    assert request.model_id == "fallback-model"


def test_model_request_preserves_an_optional_output_budget_override() -> None:
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="检查项目状态。",
        max_output_tokens=64_000,
    )

    assert request.max_output_tokens == 64_000


@pytest.mark.parametrize("system_prompt", ["", "   "])
def test_model_request_rejects_blank_system_prompt(system_prompt: str) -> None:
    with pytest.raises(ValueError, match="字段“system_prompt”必须是非空字符串"):
        ModelRequest(
            session_id="session-1",
            run_id="run-1",
            user_input="检查项目状态。",
            system_prompt=system_prompt,
        )


@pytest.mark.parametrize("model_id", ["", "   "])
def test_model_request_rejects_blank_model_override(model_id: str) -> None:
    with pytest.raises(ValueError, match="字段“model_id”必须是非空字符串"):
        ModelRequest(
            session_id="session-1",
            run_id="run-1",
            user_input="检查项目状态。",
            model_id=model_id,
        )


@pytest.mark.parametrize("max_output_tokens", [0, -1, True, "64000"])
def test_model_request_rejects_an_invalid_output_budget_override(
    max_output_tokens: object,
) -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        ModelRequest(
            session_id="session-1",
            run_id="run-1",
            user_input="检查项目状态。",
            max_output_tokens=max_output_tokens,  # type: ignore[arg-type]
        )
