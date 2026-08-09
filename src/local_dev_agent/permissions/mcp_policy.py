"""MCP 外接工具的保守权限策略装饰器。"""

from __future__ import annotations

from local_dev_agent.mcp import McpToolAnnotations, McpToolAnnotationsCatalog

from .ports import ApprovalPrompt, PermissionPolicy
from .schema import PermissionContext, PermissionResult


class McpPermissionPolicy:
    """在既有策略允许后，仍要求用户确认所有 MCP 连接与外部工具调用。"""

    def __init__(
        self,
        fallback_policy: PermissionPolicy,
        annotations_catalog: McpToolAnnotationsCatalog,
        *,
        approval_prompt: ApprovalPrompt,
    ) -> None:
        if not isinstance(fallback_policy, PermissionPolicy):
            raise TypeError("fallback_policy 必须实现 PermissionPolicy。")
        if not isinstance(annotations_catalog, McpToolAnnotationsCatalog):
            raise TypeError("annotations_catalog 必须实现 McpToolAnnotationsCatalog。")
        if not callable(approval_prompt):
            raise TypeError("approval_prompt 必须可调用。")
        self._fallback_policy = fallback_policy
        self._annotations_catalog = annotations_catalog
        self._approval_prompt = approval_prompt

    def check(self, context: PermissionContext) -> PermissionResult:
        """先保留现有拒绝规则，再对外接协议边界做显式确认。"""

        fallback_result = self._fallback_policy.check(context)
        if fallback_result.decision.value == "deny":
            return fallback_result

        reason = self._approval_reason(context)
        if reason is None:
            return fallback_result
        if self._approval_prompt(context, reason):
            return PermissionResult.allow()
        return PermissionResult.deny(f"用户拒绝执行：{reason}")

    def _approval_reason(self, context: PermissionContext) -> str | None:
        tool_name = context.request.name
        if tool_name == "connect_mcp":
            server_name = context.request.arguments.get("name")
            return f"将连接已配置的 MCP Server“{server_name}”并把外部工具加入当前 Lead 工具池。"
        if not tool_name.startswith("mcp__"):
            return None

        annotations = self._annotations_catalog.get_annotations(tool_name)
        if annotations is None:
            return f"外部 MCP 工具“{tool_name}”缺少风险标注，必须确认后才能调用。"
        return _format_mcp_tool_reason(tool_name, annotations)


def _format_mcp_tool_reason(tool_name: str, annotations: McpToolAnnotations) -> str:
    """把不可信但已校验的 MCP annotations 转为清晰的确认理由。"""

    risk_parts: list[str] = []
    if annotations.destructive_hint:
        risk_parts.append("可能执行破坏性操作")
    elif annotations.read_only_hint:
        risk_parts.append("声明为只读操作")
    else:
        risk_parts.append("未声明为只读操作")
    if annotations.open_world_hint:
        risk_parts.append("可能访问或影响外部系统")
    if annotations.idempotent_hint:
        risk_parts.append("声明可安全重试")
    else:
        risk_parts.append("未声明可安全重试")
    return (
        f"外部 MCP 工具“{tool_name}”{('；'.join(risk_parts))}；"
        "这些标注仅为 Server 提示，仍需用户确认。"
    )
