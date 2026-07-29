"""S11 首次输出截断时的预算升级契约。"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_ESCALATED_MAX_OUTPUT_TOKENS = 64_000
"""与 learnClaudeCode S11 一致的首次截断升级输出预算。"""

DEFAULT_MAX_OUTPUT_CONTINUATIONS = 3
"""升级输出预算后允许的临时纯文本续写次数。"""

OUTPUT_CONTINUATION_PROMPT = (
    "输出因 token 限制被截断。请直接从中断处继续，不要道歉、不要重复或总结前文。"
)
"""仅用于临时派生请求的续写提示，绝不写入 Conversation Transcript。"""


@dataclass(frozen=True, slots=True)
class OutputBudgetUpgradePolicy:
    """为首次输出截断提供固定的、更高输出预算，不承担重试编排。"""

    initial_max_output_tokens: int
    escalated_max_output_tokens: int = DEFAULT_ESCALATED_MAX_OUTPUT_TOKENS

    def __post_init__(self) -> None:
        """拒绝无意义的升级预算，保证 Provider 请求始终可解释。"""

        for field_name in (
            "initial_max_output_tokens",
            "escalated_max_output_tokens",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} 必须是正整数。")

    @property
    def can_upgrade(self) -> bool:
        """仅在固定升级值确实高于初始预算时启用恢复，避免降低用户配置。"""

        return self.escalated_max_output_tokens > self.initial_max_output_tokens


@dataclass(frozen=True, slots=True)
class OutputContinuationPolicy:
    """限制升级后纯文本截断的临时续写次数与提示内容。"""

    max_continuations: int = DEFAULT_MAX_OUTPUT_CONTINUATIONS
    prompt: str = OUTPUT_CONTINUATION_PROMPT

    def __post_init__(self) -> None:
        """将恢复次数和提示固定为可审计、不可变的运行时边界。"""

        if (
            isinstance(self.max_continuations, bool)
            or not isinstance(self.max_continuations, int)
            or self.max_continuations < 1
        ):
            raise ValueError("max_continuations 必须是正整数。")
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt 必须是非空字符串。")
