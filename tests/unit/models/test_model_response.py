from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.models.ports import (
    ModelResponse,
    StopReason,
    TextBlock,
    ToolUseBlock,
)


def test_model_response_represents_an_anthropic_style_text_completion() -> None:
    response = ModelResponse(
        stop_reason=StopReason.END_TURN,
        content=(TextBlock("项目状态正常。"), TextBlock("可以继续下一步。")),
    )

    assert response.text == "项目状态正常。可以继续下一步。"
    assert [block.text for block in response.text_blocks] == [
        "项目状态正常。",
        "可以继续下一步。",
    ]


def test_model_response_represents_an_anthropic_style_tool_use() -> None:
    tool_use = ToolUseBlock(
        tool_use_id="toolu-1",
        name="read_file",
        input={"path": "README.md"},
    )
    response = ModelResponse(
        stop_reason=StopReason.TOOL_USE,
        content=(tool_use,),
    )

    assert response.content == (tool_use,)
    assert response.text == ""
    with pytest.raises(TypeError):
        tool_use.input["path"] = "其他文件"  # type: ignore[index]


def test_tool_use_stop_reason_requires_a_tool_use_block() -> None:
    with pytest.raises(ValueError, match="必须包含工具调用块"):
        ModelResponse(
            stop_reason=StopReason.TOOL_USE,
            content=(TextBlock("我准备调用工具。"),),
        )


def test_model_response_cannot_be_mutated_directly() -> None:
    response = ModelResponse.text_completion("项目状态正常。")

    with pytest.raises(FrozenInstanceError):
        response.stop_reason = StopReason.TOOL_USE  # type: ignore[misc]
