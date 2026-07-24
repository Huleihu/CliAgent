"""将简单权限策略适配到 PreToolUse Hook。"""

from __future__ import annotations

from local_dev_agent.hooks import HookContext, HookResult, PreToolUseContext

from .ports import PermissionPolicy
from .schema import PermissionContext, PermissionDecision, PermissionResult


class PermissionHook:
    """在工具实际执行前调用权限策略。"""

    name = "simple-permission"

    def __init__(self, policy: PermissionPolicy) -> None:
        if not isinstance(policy, PermissionPolicy):
            raise TypeError("PermissionHook 必须使用 PermissionPolicy。")
        self._policy = policy

    def handle(self, context: HookContext) -> HookResult:
        """把权限允许或拒绝结果转换为 Hook 控制结果。"""

        if not isinstance(context, PreToolUseContext):
            raise TypeError("PermissionHook 只能处理 PreToolUseContext。")
        result = self._policy.check(
            PermissionContext(
                session_id=context.session_id,
                run_id=context.run_id,
                step_id=context.step_id,
                request=context.request,
            )
        )
        if not isinstance(result, PermissionResult):
            raise TypeError("PermissionPolicy 必须返回 PermissionResult。")
        if result.decision is PermissionDecision.DENY:
            return HookResult.block(result.reason or "权限策略拒绝执行。")
        return HookResult.continue_()
