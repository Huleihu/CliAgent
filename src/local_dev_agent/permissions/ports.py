"""权限策略与审批交互的最小可替换端口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .schema import PermissionContext, PermissionResult

ApprovalPrompt = Callable[[PermissionContext, str], bool]


@runtime_checkable
class PermissionPolicy(Protocol):
    """在工具执行前返回最终允许或拒绝结果。"""

    def check(self, context: PermissionContext) -> PermissionResult:
        """检查一次已经通过工具参数校验的调用。"""
