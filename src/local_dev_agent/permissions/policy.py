"""learnClaudeCode S3 风格的简单三道门权限策略。"""

from __future__ import annotations

from pathlib import Path

from .ports import ApprovalPrompt
from .schema import PermissionContext, PermissionResult

_DENY_PATTERNS = (
    "rm -rf /",
    "sudo",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    "> /dev/sda",
)
_RISKY_BASH_PATTERNS = ("rm ", "> /etc/", "chmod 777")
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


def ask_user(context: PermissionContext, reason: str) -> bool:
    """在终端询问用户是否允许本次工具调用，默认拒绝。"""

    print(f"\n⚠  {reason}")
    print(f"   工具：{context.request.name}({dict(context.request.arguments)})")
    choice = input("   允许本次执行？[y/N] ").strip().lower()
    return choice in {"y", "yes"}


class SimplePermissionPolicy:
    """依次执行硬拒绝、风险规则和用户确认，未命中时默认允许。"""

    def __init__(
        self,
        workspace: Path,
        *,
        approval_prompt: ApprovalPrompt = ask_user,
    ) -> None:
        self._workspace = workspace.resolve()
        self._approval_prompt = approval_prompt

    def check(self, context: PermissionContext) -> PermissionResult:
        """按固定三道门检查一次工具调用。"""

        hard_deny_reason = self._check_deny_list(context)
        if hard_deny_reason is not None:
            return PermissionResult.deny(hard_deny_reason)

        approval_reason = self._check_rules(context)
        if approval_reason is None:
            return PermissionResult.allow()
        if self._approval_prompt(context, approval_reason):
            return PermissionResult.allow()
        return PermissionResult.deny(f"用户拒绝执行：{approval_reason}")

    @staticmethod
    def _check_deny_list(context: PermissionContext) -> str | None:
        if context.request.name != "bash":
            return None
        command = context.request.arguments.get("command")
        if not isinstance(command, str):
            return None
        for pattern in _DENY_PATTERNS:
            if pattern in command:
                return f"命令包含禁止执行的模式“{pattern}”。"
        return None

    def _check_rules(self, context: PermissionContext) -> str | None:
        request = context.request
        if request.name in _WRITE_TOOLS:
            path = request.arguments.get("path")
            if isinstance(path, str):
                target = (self._workspace / path).resolve()
                if not target.is_relative_to(self._workspace):
                    return "工具将写入工作区之外。"

        if request.name == "bash":
            command = request.arguments.get("command")
            if isinstance(command, str) and any(
                pattern in command for pattern in _RISKY_BASH_PATTERNS
            ):
                return "命令可能执行破坏性操作。"
        return None
