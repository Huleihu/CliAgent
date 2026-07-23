"""基于 Anthropic 兼容协议访问 DeepSeek 的模型适配器。"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .deepseek_settings import DeepSeekSettings
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


class DeepSeekModelError(RuntimeError):
    """当 DeepSeek 调用或响应无法映射到内部协议时抛出。"""


class DeepSeekAnthropicModelClient:
    """使用 DeepSeek 的 Anthropic 兼容接口实现 ModelClient。"""

    def __init__(self, settings: DeepSeekSettings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        """调用 DeepSeek，并将兼容响应转换为内部内容块协议。"""

        messages = self._map_request_messages(request)
        try:
            response = self._client.messages.create(
                model=self._settings.model,
                max_tokens=self._settings.max_tokens,
                messages=messages,
            )
        except Exception as error:
            raise DeepSeekModelError("DeepSeek 模型调用失败。") from error

        return self._map_response(response)

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
            content = tuple(
                self._map_content_block(block)
                for block in response.content
                if getattr(block, "type", None) != "thinking"
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
