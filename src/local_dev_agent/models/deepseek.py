"""基于 Anthropic 兼容协议访问 DeepSeek 的模型适配器。"""

from __future__ import annotations

from typing import Any

import anthropic

from .deepseek_settings import DeepSeekSettings
from .ports import (
    ModelContentBlock,
    ModelRequest,
    ModelResponse,
    StopReason,
    TextBlock,
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

        try:
            response = self._client.messages.create(
                model=self._settings.model,
                max_tokens=self._settings.max_tokens,
                messages=[{"role": "user", "content": request.user_input}],
            )
        except Exception as error:
            raise DeepSeekModelError("DeepSeek 模型调用失败。") from error

        return self._map_response(response)

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
