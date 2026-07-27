import pytest

from local_dev_agent.context import ContextInputSnapshot
from local_dev_agent.context.summary import (
    HISTORY_SUMMARY_REQUIREMENTS,
    HistorySummaryGenerationError,
    ModelConversationSummarizer,
)
from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    ModelResponse,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from local_dev_agent.models.fake import FakeModel


def _snapshot() -> ContextInputSnapshot:
    return ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("检查 README。"),),
            ),
        ),
    )


def test_model_conversation_summarizer_requests_plain_text_without_tools() -> None:
    model = FakeModel(ModelResponse.text_completion("当前目标：检查 README。"))

    summary = ModelConversationSummarizer(model).summarize(_snapshot())

    request = model.requests[0]
    assert summary == "当前目标：检查 README。"
    assert request.tools == ()
    assert request.system_prompt == HISTORY_SUMMARY_REQUIREMENTS
    assert request.conversation[0].role is MessageRole.USER
    assert "待摘要的历史消息" in request.conversation[0].content[0].text  # type: ignore[union-attr]
    assert "检查 README。" in request.conversation[0].content[0].text  # type: ignore[union-attr]


def test_model_conversation_summarizer_rejects_non_terminal_or_empty_response() -> None:
    response = ModelResponse(
        stop_reason=StopReason.TOOL_USE,
        content=(
            ToolUseBlock(tool_use_id="toolu-1", name="read_file", input={}),
        ),
    )

    with pytest.raises(HistorySummaryGenerationError, match="模型未返回可用的历史摘要"):
        ModelConversationSummarizer(FakeModel(response)).summarize(_snapshot())
