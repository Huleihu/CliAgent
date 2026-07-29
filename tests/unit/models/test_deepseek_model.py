from dataclasses import dataclass

import anthropic
import httpx
import pytest

from local_dev_agent.models import (
    DeepSeekAnthropicModelClient,
    DeepSeekConfigurationError,
    DeepSeekModelError,
    DeepSeekSettings,
    ModelConnectionError,
    ModelContextWindowExceededError,
    ModelOverloadedError,
    ModelRateLimitError,
    ModelTimeoutError,
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


class FakeProviderError(RuntimeError):
    """模拟兼容 Provider 已解析的状态码与结构化错误体。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


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


def test_settings_reads_an_optional_fallback_model_from_environment() -> None:
    settings = DeepSeekSettings.from_environment(
        {
            "DEEPSEEK_API_KEY": "测试密钥",
            "DEEPSEEK_ANTHROPIC_BASE_URL": "https://example.test/anthropic",
            "DEEPSEEK_MODEL": "primary-model",
            "DEEPSEEK_FALLBACK_MODEL": "fallback-model",
            "DEEPSEEK_MAX_TOKENS": "2048",
        }
    )

    assert settings.fallback_model == "fallback-model"


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


def test_model_client_uses_a_request_model_override_when_provided() -> None:
    client = FakeAnthropicClient(
        FakeMessage(stop_reason="end_turn", content=[FakeTextContent("状态正常。")])
    )
    model = DeepSeekAnthropicModelClient(_settings(), client=client)

    model.generate(
        ModelRequest(
            session_id="session-1",
            run_id="run-1",
            user_input="检查项目状态。",
            model_id="fallback-model",
        )
    )

    assert client.messages.calls[0]["model"] == "fallback-model"


def test_model_client_uses_a_request_output_budget_override_when_provided() -> None:
    client = FakeAnthropicClient(
        FakeMessage(stop_reason="end_turn", content=[FakeTextContent("状态正常。")])
    )
    model = DeepSeekAnthropicModelClient(_settings(), client=client)

    model.generate(
        ModelRequest(
            session_id="session-1",
            run_id="run-1",
            user_input="检查项目状态。",
            max_output_tokens=64_000,
        )
    )

    assert client.messages.calls[0]["max_tokens"] == 64_000


def test_model_client_disables_sdk_implicit_retries(monkeypatch) -> None:
    construction_arguments: list[dict[str, object]] = []

    class ConstructedClient:
        def __init__(self, **kwargs: object) -> None:
            construction_arguments.append(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", ConstructedClient)

    DeepSeekAnthropicModelClient(_settings())

    assert construction_arguments == [
        {
            "api_key": "测试密钥",
            "base_url": "https://api.deepseek.com/anthropic",
            "max_retries": 0,
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


def test_model_client_sends_an_optional_system_prompt_only_when_configured() -> None:
    client = FakeAnthropicClient(
        FakeMessage(stop_reason="end_turn", content=[FakeTextContent("已完成。")])
    )
    model = DeepSeekAnthropicModelClient(_settings(), client=client)

    model.generate(_request())
    model.generate(
        ModelRequest(
            session_id="session-1",
            run_id="run-2",
            user_input="更新待办清单。",
            system_prompt="多步骤任务先维护待办清单。",
        )
    )

    assert "system" not in client.messages.calls[0]
    assert client.messages.calls[1]["system"] == "多步骤任务先维护待办清单。"


def test_model_client_wraps_provider_failure_in_chinese_error() -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(RuntimeError("网络不可用")),
    )

    with pytest.raises(DeepSeekModelError, match="DeepSeek 模型调用失败"):
        model.generate(_request())


@pytest.mark.parametrize(
    "error",
    [
        FakeProviderError("请求体过大", status_code=413),
        FakeProviderError(
            "兼容端点返回结构化超限代码",
            status_code=400,
            body={"error": {"type": "request_too_large"}},
        ),
        FakeProviderError(
            "兼容端点返回结构化超限代码",
            status_code=400,
            body={"error": {"code": "prompt_too_long"}},
        ),
        anthropic.RequestTooLargeError(
            "请求体过大",
            response=httpx.Response(
                413,
                request=httpx.Request(
                    "POST",
                    "https://api.deepseek.com/anthropic/messages",
                ),
            ),
            body={"error": {"type": "request_too_large"}},
        ),
    ],
)
def test_model_client_maps_only_explicit_context_limit_signals(
    error: Exception,
) -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(error),
    )

    with pytest.raises(ModelContextWindowExceededError) as error_info:
        model.generate(_request())

    assert error_info.value.__cause__ is error


@pytest.mark.parametrize(
    ("provider_error", "expected_error"),
    [
        (
            anthropic.APIConnectionError(
                message="网络不可用",
                request=httpx.Request(
                    "POST",
                    "https://api.deepseek.com/anthropic/messages",
                ),
            ),
            ModelConnectionError,
        ),
        (
            anthropic.APITimeoutError(
                request=httpx.Request(
                    "POST",
                    "https://api.deepseek.com/anthropic/messages",
                ),
            ),
            ModelTimeoutError,
        ),
        (
            FakeProviderError("速率限制", status_code=429),
            ModelRateLimitError,
        ),
        (
            FakeProviderError("服务过载", status_code=529),
            ModelOverloadedError,
        ),
    ],
)
def test_model_client_maps_only_explicit_transient_signals(
    provider_error: Exception,
    expected_error: type[Exception],
) -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(provider_error),
    )

    with pytest.raises(expected_error) as error_info:
        model.generate(_request())

    assert error_info.value.__cause__ is provider_error


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (429, ModelRateLimitError),
        (529, ModelOverloadedError),
    ],
)
def test_model_client_preserves_numeric_retry_after(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    provider_error = anthropic.APIStatusError(
        "测试瞬态错误",
        response=httpx.Response(
            status_code,
            headers={"retry-after": "2.5"},
            request=httpx.Request(
                "POST",
                "https://api.deepseek.com/anthropic/messages",
            ),
        ),
        body={"error": {"type": "测试错误"}},
    )
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(provider_error),
    )

    with pytest.raises(expected_error) as error_info:
        model.generate(_request())

    assert error_info.value.retry_after_seconds == 2.5


def test_model_client_ignores_invalid_retry_after() -> None:
    provider_error = anthropic.APIStatusError(
        "测试速率限制",
        response=httpx.Response(
            429,
            headers={"retry-after": "later"},
            request=httpx.Request(
                "POST",
                "https://api.deepseek.com/anthropic/messages",
            ),
        ),
        body={"error": {"type": "rate_limit_error"}},
    )
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(provider_error),
    )

    with pytest.raises(ModelRateLimitError) as error_info:
        model.generate(_request())

    assert error_info.value.retry_after_seconds is None


@pytest.mark.parametrize(
    "error",
    [
        FakeProviderError(
            "请求格式错误",
            status_code=400,
            body={"error": {"type": "invalid_request_error"}},
        ),
        FakeProviderError(
            "认证失败",
            status_code=401,
            body={"error": {"type": "authentication_error"}},
        ),
        FakeProviderError(
            "结构化正文不能替代明确的限流状态",
            status_code=400,
            body={"error": {"type": "rate_limit_error"}},
        ),
        FakeProviderError(
            "服务端错误",
            status_code=500,
            body={"error": {"type": "api_error"}},
        ),
        FakeProviderError("文本中碰巧出现 prompt_too_long"),
        RuntimeError("文本中碰巧出现 429"),
        RuntimeError("文本中碰巧出现 overloaded"),
        anthropic.AuthenticationError(
            "认证失败",
            response=httpx.Response(
                401,
                request=httpx.Request(
                    "POST",
                    "https://api.deepseek.com/anthropic/messages",
                ),
            ),
            body={"error": {"type": "authentication_error"}},
        ),
    ],
)
def test_model_client_keeps_non_context_limit_provider_failures_as_deepseek_error(
    error: Exception,
) -> None:
    model = DeepSeekAnthropicModelClient(
        _settings(),
        client=FakeAnthropicClient(error),
    )

    with pytest.raises(DeepSeekModelError) as error_info:
        model.generate(_request())

    assert error_info.value.__cause__ is error


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
