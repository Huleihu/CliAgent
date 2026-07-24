"""Hook 实现与运行时触发器之间的稳定端口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .schema import (
    HookResult,
    PostToolUseContext,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)

HookContext = (
    UserPromptSubmitContext
    | PreToolUseContext
    | PostToolUseContext
    | StopContext
)


@runtime_checkable
class Hook(Protocol):
    """可按事件注册并接收冻结上下文的最小 Hook 端口。"""

    @property
    def name(self) -> str:
        """返回在所属事件内唯一的可读名称。"""

    def handle(self, context: HookContext) -> HookResult:
        """处理一次事件并明确继续默认流程或阻止该流程。"""
