from dataclasses import dataclass

import pytest

from local_dev_agent.models import (
    DeepSeekAnthropicModelClient,
    DeepSeekConfigurationError,
    DeepSeekModelError,
    DeepSeekSettings,
)
from local_dev_agent.models.ports import (
    MessageRole,
    ModelMessage,
    ModelRequest,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.tools.schema import ToolDefinition


@dataclass
class FakeTextContent:
    """模拟 Anthropic SDK 返回的文本内容块。"""

    text: str
    type: str = "text"


@dataclass
class FakeToolUseContent:
    """模拟 Anthropic SDK 返回的工具调用内容块。"""

    id: str
    name: str
    input: dict[str, object]
    type: str = "tool_use"


@dataclass
class FakeThinkingContent:
    """模拟 DeepSeek 返回、但当前 Runtime 不持久化的思考块。"""

    type: str = "thinking"


@dataclass
class FakeMessage:
    """模拟 Anthropic SDK 返回的消息。"""

    stop_reason: str
    content: list[object]


class FakeMessages:
    """记录 SDK 请求并返回预设消息。"""

    def __init__(self, response: FakeMessage | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeMessage:
        """记录请求，按配置返回消息或抛出异常。"""

        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeAnthropicClient:
    """提供与适配器所需最小接口一致的 SDK 假对象。"""

    def __init__(self, response: FakeMessage | Exception) -> None:
        self.messages = FakeMessages(response)


def _settings() -> DeepSeekSettings:
    return DeepSeekSettings(
        api_key="测试密钥",
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-v4-flash",
        max_tokens=1024,
    )


def _request() -> ModelRequest:
    return ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="检查项目状态。",
    )


def test_settings_reads_all_deepseek_values_from_environment() -> None:
    settings = DeepSeekSettings.from_environment(
        {
            "DEEPSEEK_API_KEY": "测试密钥",
            "DEEPSEEK_ANTHROPIC_BASE_URL": "https://example.test/anthropic",
            "DEEPSEEK_MODEL": "deepseek-test",
            "DEEPSEEK_MAX_TOKENS": "2048",
        }
    )

    assert settings == DeepSeekSettings(
        api_key="测试密钥",
        base_url="https://example.test/anthropic",
        model="deepseek-test",
        max_tokens=2048,
    )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({}, "DEEPSEEK_MAX_TOKENS"),
        (
            {
                "DEEPSEEK_API_KEY": "key",
                "DEEPSEEK_ANTHROPIC_BASE_URL": "url",
                "DEEPSEEK_MODEL": "model",
                "DEEPSEEK_MAX_TOKENS": "0",
            },
            "必须是正整数",
        ),
    ],
)
def test_settings_rejects_missing_or_invalid_values(
    values: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(DeepSeekConfigurationError, match=message):
        DeepSeekSettings.from_environment(values)


def test_model_client_maps_a_text_response_and_sends_configured_request() -> None:
    client = FakeAnthropicClient(
        FakeMessage(stop_reason="end_turn", content=[FakeTextContent("状态正常。")])
    )
    model = DeepSeekAnthropicModelClient(_settings(), client=client)

    response = model.generate(_request())

    assert response.stop_reason is StopReason.END_TURN
    assert response.content == (TextBlock("状态正常。"),)
    assert client.messages.calls == [
        {
            "model": "deepseek-v4-flash",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "检查项目状态。"}],
            "thinking": {"type": "disabled"},
        }
    ]


def test_model_client_maps_a_tool_use_response() -> None:
    client = FakeAnthropicClient(
        FakeMessage(
            stop_reason="tool_use",
            content=[
                FakeToolUseContent(
                    id="toolu-1",
                    name="read_file",
                    input={"path": "README.md"},
                )
            ],
        )
    )

    response = DeepSeekAnthropicModelClient(_settings(), client=client).generate(
        _request()
    )

    assert response.stop_reason is StopReason.TOOL_USE
    assert response.content == (
        ToolUseBlock(
            tool_use_id="toolu-1",
            name="read_file",
            input={"path": "README.md"},
        ),
    )


def test_model_client_serializes_multi_turn_messages_and_tool_results() -> None:
    client = FakeAnthropicClient(
        FakeMessage(stop_reason="end_turn", content=[FakeTextContent("已完成。")])
    )
    request = ModelRequest.from_messages(
        session_id="session-1",
        run_id="run-1",
        messages=(
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
                        is_error=False,
                    ),
                ),
            ),
        ),
    )

    DeepSeekAnthropicModelClient(_settings(), client=client).generate(request)

    assert client.messages.calls[0]["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "读取 README。"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu-1",
                    "content": '{"content": "项目说明"}',
                    "is_error": False,
                }
            ],
        },
    ]
    assert client.messages.calls[0]["thinking"] == {"type": "disabled"}


def test_model_client_declares_registered_tool_definitions_when_requested() -> None:
    client = FakeAnthropicClient(
        FakeMessage(stop_reason="end_turn", content=[FakeTextContent("已完成。")])
    )
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="读取 README。",
        tools=(
            ToolDefinition(
                name="read_file",
                description="读取工作区中的文本文件。",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ),
    )

    DeepSeekAnthropicModelClient(_settings(), client=client).generate(request)

    assert client.messages.calls[0]["tools"] == [
        {
            "name": "read_file",
            "description": "读取工作区中的文本文件。",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]


def test_model_client_wraps_provider_failure_in_chinese_error() -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(RuntimeError("网络不可用")),
    )

    with pytest.raises(DeepSeekModelError, match="DeepSeek 模型调用失败"):
        model.generate(_request())


def test_model_client_rejects_an_unknown_stop_reason() -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(
            FakeMessage(stop_reason="unknown", content=[FakeTextContent("内容")])
        ),
    )

    with pytest.raises(DeepSeekModelError, match="不受支持的停止原因"):
        model.generate(_request())


def test_model_client_explains_a_thinking_only_response_without_exposing_its_content() -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(
            FakeMessage(stop_reason="end_turn", content=[FakeThinkingContent()])
        ),
    )

    with pytest.raises(DeepSeekModelError, match="仅返回了思考内容或空内容"):
        model.generate(_request())
