"""将历史消息收束为可继续工作的摘要，隔离摘要生成策略。"""

from __future__ import annotations

import json
from typing import Protocol

from local_dev_agent.models import (
    MessageRole,
    ModelClient,
    ModelMessage,
    ModelRequest,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from .budget import ContextInputSnapshot


HISTORY_SUMMARY_REQUIREMENTS = """请生成用于继续本地开发任务的简洁历史摘要。

必须保留：当前目标、关键发现与决策、已读取或修改的文件、剩余工作、用户约束、工具结果与错误的必要结论。只输出摘要文本，不调用工具。"""
"""供后续模型摘要适配器使用的稳定摘要要求，不属于用户消息。"""


class ConversationSummarizer(Protocol):
    """将完整上下文快照转换为可继续执行的纯文本摘要。"""

    def summarize(self, snapshot: ContextInputSnapshot) -> str:
        """返回非空摘要；实现方不得通过此端口触发工具调用。"""


class HistorySummaryGenerationError(RuntimeError):
    """当模型未返回可用的纯文本历史摘要时抛出。"""


class ModelConversationSummarizer:
    """复用既有 ModelClient 生成纯文本历史摘要，不向摘要请求声明工具。"""

    def __init__(self, model: ModelClient) -> None:
        if not hasattr(model, "generate"):
            raise ValueError("model 必须提供 generate 方法。")
        self._model = model

    def summarize(self, snapshot: ContextInputSnapshot) -> str:
        """将历史编码为单条用户消息，拒绝工具调用或空摘要响应。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        response = self._model.generate(
            ModelRequest.from_messages(
                session_id=snapshot.session_id,
                run_id=snapshot.run_id,
                messages=(
                    ModelMessage(
                        role=MessageRole.USER,
                        content=(TextBlock(self._format_source_messages(snapshot)),),
                    ),
                ),
                system_prompt=HISTORY_SUMMARY_REQUIREMENTS,
            )
        )
        summary = response.text.strip()
        if response.stop_reason is not StopReason.END_TURN or not summary:
            raise HistorySummaryGenerationError("模型未返回可用的历史摘要。")
        return summary

    @classmethod
    def _format_source_messages(cls, snapshot: ContextInputSnapshot) -> str:
        """保留消息角色、内容块和顺序，避免摘要器猜测工具调用关联。"""

        source = [cls._message_to_json(message) for message in snapshot.messages]
        return "待摘要的历史消息：\n" + json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _message_to_json(cls, message: ModelMessage) -> dict[str, object]:
        return {
            "role": message.role.value,
            "content": [cls._block_to_json(block) for block in message.content],
        }

    @staticmethod
    def _block_to_json(block: object) -> dict[str, object]:
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
                "content": dict(block.content),
                "is_error": block.is_error,
            }
        raise HistorySummaryGenerationError("历史消息包含不受支持的内容块。")


class HistorySummaryCompactor:
    """L4：以摘要替换派生消息视图，保留原始快照作为外部事实来源。"""

    def __init__(self, summarizer: ConversationSummarizer) -> None:
        if not hasattr(summarizer, "summarize"):
            raise ValueError("summarizer 必须提供 summarize 方法。")
        self._summarizer = summarizer

    def compact(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        """生成摘要消息；不修改输入快照或其背后的 Conversation Transcript。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        summary = self._summarizer.summarize(snapshot)
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("历史摘要必须是非空字符串。")
        summary_message = ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock(f"[已压缩的历史摘要]\n\n{summary.strip()}"),),
        )
        return ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=(summary_message,),
            system_prompt=snapshot.system_prompt,
            tools=snapshot.tools,
        )
