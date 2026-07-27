"""为模型请求生成可替换、可审计的上下文预算报告。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from local_dev_agent.models import (
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.tools.schema import ToolDefinition


def _require_nonempty_text(field_name: str, value: str) -> str:
    """规范化关联标识，避免预算报告失去所属请求。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


def _require_nonnegative_integer(field_name: str, value: int) -> int:
    """拒绝布尔值和负数，保持 token 预算计算可解释。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"字段“{field_name}”必须是非负整数。")
    return value


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """一次模型请求为输入上下文预留的显式 token 边界。"""

    context_window_tokens: int
    max_output_tokens: int
    safety_margin_tokens: int = 13_000

    def __post_init__(self) -> None:
        """确保输出和安全余量不会耗尽整个上下文窗口。"""

        context_window_tokens = _require_nonnegative_integer(
            "context_window_tokens",
            self.context_window_tokens,
        )
        max_output_tokens = _require_nonnegative_integer(
            "max_output_tokens",
            self.max_output_tokens,
        )
        safety_margin_tokens = _require_nonnegative_integer(
            "safety_margin_tokens",
            self.safety_margin_tokens,
        )
        if context_window_tokens < 1:
            raise ValueError("字段“context_window_tokens”必须大于零。")
        if context_window_tokens <= max_output_tokens + safety_margin_tokens:
            raise ValueError("上下文窗口必须保留至少一个输入 token。")

    @property
    def available_input_tokens(self) -> int:
        """返回扣除预期输出和安全余量后的输入预算。"""

        return (
            self.context_window_tokens
            - self.max_output_tokens
            - self.safety_margin_tokens
        )


@dataclass(frozen=True, slots=True)
class ContextInputSnapshot:
    """一次上下文装配前的不可变输入快照，不等同于持久化 Transcript。"""

    session_id: str
    run_id: str
    messages: tuple[ModelMessage, ...]
    system_prompt: str | None = None
    tools: tuple[ToolDefinition, ...] = ()

    def __post_init__(self) -> None:
        """固定估算来源，防止装配期间请求内容被调用方静默替换。"""

        object.__setattr__(self, "session_id", _require_nonempty_text("session_id", self.session_id))
        object.__setattr__(self, "run_id", _require_nonempty_text("run_id", self.run_id))
        if not isinstance(self.messages, tuple) or not self.messages:
            raise ValueError("字段“messages”必须是非空 ModelMessage 元组。")
        if not all(isinstance(message, ModelMessage) for message in self.messages):
            raise ValueError("字段“messages”必须是非空 ModelMessage 元组。")
        if self.system_prompt is not None:
            object.__setattr__(
                self,
                "system_prompt",
                _require_nonempty_text("system_prompt", self.system_prompt),
            )
        if not isinstance(self.tools, tuple) or not all(
            isinstance(tool, ToolDefinition) for tool in self.tools
        ):
            raise ValueError("字段“tools”必须是 ToolDefinition 元组。")


@dataclass(frozen=True, slots=True)
class ContextBudgetReport:
    """一次估算的分区 token 用量和是否超预算的结论。"""

    budget: ContextBudget
    system_prompt_tokens: int
    tool_definition_tokens: int
    message_tokens: int

    def __post_init__(self) -> None:
        """保证报告的分区数值可求和，方便后续压缩决策审计。"""

        if not isinstance(self.budget, ContextBudget):
            raise ValueError("字段“budget”必须是 ContextBudget 对象。")
        for field_name in (
            "system_prompt_tokens",
            "tool_definition_tokens",
            "message_tokens",
        ):
            _require_nonnegative_integer(field_name, getattr(self, field_name))

    @property
    def estimated_input_tokens(self) -> int:
        """返回全部会进入模型请求的输入 token 估算值。"""

        return (
            self.system_prompt_tokens
            + self.tool_definition_tokens
            + self.message_tokens
        )

    @property
    def remaining_input_tokens(self) -> int:
        """返回可用预算与估算用量之差；负值表示需要压缩。"""

        return self.budget.available_input_tokens - self.estimated_input_tokens

    @property
    def exceeds_budget(self) -> bool:
        """明确暴露压缩触发条件，避免调用方自行重复比较。"""

        return self.remaining_input_tokens < 0


class ContextBudgetEstimator(Protocol):
    """将规范化模型请求转换为预算报告的可替换端口。"""

    def estimate(
        self,
        snapshot: ContextInputSnapshot,
        budget: ContextBudget,
    ) -> ContextBudgetReport:
        """基于同一输入快照生成一份确定性的预算报告。"""


class Utf8ByteContextBudgetEstimator:
    """用 UTF-8 字节数近似 token 的确定性默认实现。"""

    _BYTES_PER_TOKEN = 4

    def estimate(
        self,
        snapshot: ContextInputSnapshot,
        budget: ContextBudget,
    ) -> ContextBudgetReport:
        """分别计算系统提示、工具声明和消息，便于定位压缩来源。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        if not isinstance(budget, ContextBudget):
            raise ValueError("字段“budget”必须是 ContextBudget 对象。")
        return ContextBudgetReport(
            budget=budget,
            system_prompt_tokens=self._estimate_text(snapshot.system_prompt or ""),
            tool_definition_tokens=self._estimate_json(
                tuple(self._tool_to_json(tool) for tool in snapshot.tools)
            ),
            message_tokens=self._estimate_json(
                tuple(self._message_to_json(message) for message in snapshot.messages)
            ),
        )

    @classmethod
    def _estimate_text(cls, value: str) -> int:
        if not value:
            return 0
        return ceil(len(value.encode("utf-8")) / cls._BYTES_PER_TOKEN)

    @classmethod
    def _estimate_json(cls, value: object) -> int:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls._estimate_text(serialized)

    @staticmethod
    def _tool_to_json(tool: ToolDefinition) -> dict[str, object]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
            "tags": tool.tags,
        }

    @staticmethod
    def _message_to_json(message: ModelMessage) -> dict[str, object]:
        return {
            "role": message.role.value,
            "content": [
                Utf8ByteContextBudgetEstimator._content_block_to_json(block)
                for block in message.content
            ],
        }

    @staticmethod
    def _content_block_to_json(block: object) -> dict[str, object]:
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
        raise ValueError("上下文消息包含不受支持的内容块。")
