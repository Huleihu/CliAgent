"""工具执行前权限检查的公共接口。"""

from .hook import PermissionHook
from .mcp_policy import McpPermissionPolicy
from .policy import SimplePermissionPolicy, ask_user
from .ports import ApprovalPrompt, PermissionPolicy
from .schema import PermissionContext, PermissionDecision, PermissionResult

__all__ = [
    "ApprovalPrompt",
    "PermissionContext",
    "PermissionDecision",
    "PermissionHook",
    "McpPermissionPolicy",
    "PermissionPolicy",
    "PermissionResult",
    "SimplePermissionPolicy",
    "ask_user",
]
