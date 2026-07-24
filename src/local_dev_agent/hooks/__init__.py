"""Agent 生命周期 Hook 的公共契约。"""

from .errors import HookValidationError
from .schema import (
    HookDecision,
    HookEvent,
    HookResult,
    PostToolUseContext,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)

__all__ = [
    "HookDecision",
    "HookEvent",
    "HookResult",
    "HookValidationError",
    "PostToolUseContext",
    "PreToolUseContext",
    "StopContext",
    "UserPromptSubmitContext",
]
