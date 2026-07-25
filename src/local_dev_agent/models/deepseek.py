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
from local_dev_agent.tools.schema import ToolDefinition


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
            raise DeepSeekModelError("DeepSeek 模型调用失败。") from error

        return self._map_response(response)

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
