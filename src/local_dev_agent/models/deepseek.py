"""基于 Anthropic 兼容协议访问 DeepSeek 的模型适配器。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import anthropic

from .deepseek_settings import DeepSeekSettings
from .errors import ModelContextWindowExceededError
from .ports import (
    ModelContentBlock,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.tools.schema import ToolDefinition


class DeepSeekModelError(RuntimeError):
    """当 DeepSeek 调用或响应无法映射到内部协议时抛出。"""


class DeepSeekAnthropicModelClient:
    """使用 DeepSeek 的 Anthropic 兼容接口实现 ModelClient。"""

    _CONTEXT_LIMIT_ERROR_CODES = frozenset({"prompt_too_long", "request_too_large"})
    """兼容端点可能使用的、可由结构化错误体确认的超限代码。"""

    def __init__(self, settings: DeepSeekSettings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        """调用 DeepSeek，并将兼容响应转换为内部内容块协议。"""

        messages = self._map_request_messages(request)
        request_parameters: dict[str, object] = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "messages": messages,
            # 当前内部协议不保存推理内容。显式关闭 thinking，避免工具回填时
            # 丢失 DeepSeek 要求继续传递的思考块，导致后续响应失去可见内容。
            "thinking": {"type": "disabled"},
        }
        if request.tools:
            request_parameters["tools"] = [
                self._map_tool_definition(tool) for tool in request.tools
            ]
        if request.system_prompt is not None:
            request_parameters["system"] = request.system_prompt
        try:
            response = self._client.messages.create(**request_parameters)
        except Exception as error:
            if self._is_context_window_exceeded(error):
                raise ModelContextWindowExceededError(
                    "DeepSeek 明确拒绝了超过上下文或请求大小限制的输入。"
                ) from error
            raise DeepSeekModelError("DeepSeek 模型调用失败。") from error

        return self._map_response(response)

    @classmethod
    def _is_context_window_exceeded(cls, error: Exception) -> bool:
        """仅接受明确状态或结构化代码，避免把普通 Provider 故障误判为超限。"""

        if cls._status_code(error) == 413:
            return True
        return cls._structured_error_code(error) in cls._CONTEXT_LIMIT_ERROR_CODES

    @staticmethod
    def _status_code(error: Exception) -> int | None:
        """兼容 SDK 直接暴露状态码或经 response 暴露状态码的两种形态。"""

        candidates = (
            getattr(error, "status_code", None),
            getattr(getattr(error, "response", None), "status_code", None),
        )
        for value in candidates:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    @staticmethod
    def _structured_error_code(error: Exception) -> str | None:
        """只读取 SDK 已解析的错误体，不依赖可能变动的自然语言错误消息。"""

        body = getattr(error, "body", None)
        if not isinstance(body, Mapping):
            return None
        candidates: tuple[Mapping[object, object], ...] = (body,)
        nested_error = body.get("error")
        if isinstance(nested_error, Mapping):
            candidates += (nested_error,)
        for candidate in candidates:
            for field_name in ("type", "code"):
                value = candidate.get(field_name)
                if isinstance(value, str):
                    return value
        return None

    @staticmethod
    def _map_tool_definition(tool: ToolDefinition) -> dict[str, object]:
        """将运行时工具定义转换为 Anthropic 兼容的工具声明。"""

        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": dict(tool.parameters),
        }

    def _map_request_messages(self, request: ModelRequest) -> list[dict[str, object]]:
        """将内部消息协议转换为 Anthropic 兼容接口的 messages 字段。"""

        if not request.messages:
            return [{"role": "user", "content": request.user_input}]
        return [self._map_message(message) for message in request.conversation]

    @classmethod
    def _map_message(cls, message: ModelMessage) -> dict[str, object]:
        """转换单条消息，保留同一消息内内容块的原始顺序。"""

        return {
            "role": message.role.value,
            "content": [cls._map_request_content_block(block) for block in message.content],
        }

    @staticmethod
    def _map_request_content_block(block: object) -> dict[str, object]:
        """转换文本、工具调用和工具结果，拒绝未支持的内部内容块。"""

        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        if isinstance(block, ToolUseBlock):
            return {
                "type": "tool_use",
                "id": block.tool_use_id,
                "name": block.name,
                "input": dict(block.input),
            }
        if isinstance(block, ToolResultBlock):
            return {
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": json.dumps(dict(block.content), ensure_ascii=False),
                "is_error": block.is_error,
            }
        raise DeepSeekModelError("模型请求包含不受支持的内容块。")

    def _map_response(self, response: Any) -> ModelResponse:
        try:
            stop_reason = StopReason(response.stop_reason)
        except (AttributeError, ValueError) as error:
            raise DeepSeekModelError("DeepSeek 返回了不受支持的停止原因。") from error

        try:
            content_types = tuple(
                getattr(block, "type", "未知") for block in response.content
            )
            content = tuple(
                self._map_content_block(block)
                for block in response.content
                if getattr(block, "type", None) != "thinking"
            )
            if not content:
                types = "、".join(str(content_type) for content_type in content_types)
                raise DeepSeekModelError(
                    f"DeepSeek 仅返回了思考内容或空内容，内容类型：{types or '无'}。"
                )
            return ModelResponse(stop_reason=stop_reason, content=content)
        except DeepSeekModelError:
            raise
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSeekModelError("DeepSeek 返回的内容不符合内部模型协议。") from error

    @staticmethod
    def _map_content_block(block: Any) -> ModelContentBlock:
        if block.type == "text":
            return TextBlock(text=block.text)
        if block.type == "tool_use":
            return ToolUseBlock(
                tool_use_id=block.id,
                name=block.name,
                input=block.input,
            )
        raise DeepSeekModelError(
            f"DeepSeek 返回了暂不支持的内容块类型“{block.type}”。"
        )
