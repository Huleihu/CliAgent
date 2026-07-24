"""Agent 生命周期 Hook 的公共契约。"""

from .errors import HookAlreadyExistsError, HookExecutionError, HookValidationError
from .ports import Hook, HookContext
from .registry import HookRegistry
from .runner import HookRunner
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
    "Hook",
    "HookAlreadyExistsError",
    "HookContext",
    "HookDecision",
    "HookEvent",
    "HookExecutionError",
    "HookRegistry",
    "HookResult",
    "HookRunner",
    "HookValidationError",
    "PostToolUseContext",
    "PreToolUseContext",
    "StopContext",
    "UserPromptSubmitContext",
]
