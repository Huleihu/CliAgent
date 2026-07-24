"""权限检查使用的不可变上下文与决策结果。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from local_dev_agent.tools import ToolCallRequest


def _require_text(field_name: str, value: str | None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


class PermissionDecision(StrEnum):
    """简单权限策略对一次工具调用作出的最终决定。"""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionContext:
    """权限策略判断工具调用时可读取的最小关联上下文。"""

    session_id: str
    run_id: str
    step_id: str
    request: ToolCallRequest

    def __post_init__(self) -> None:
        _require_text("session_id", self.session_id)
        _require_text("run_id", self.run_id)
        _require_text("step_id", self.step_id)
        if not isinstance(self.request, ToolCallRequest):
            raise TypeError("字段“request”必须是 ToolCallRequest 对象。")


@dataclass(frozen=True, slots=True)
class PermissionResult:
    """权限检查的允许或拒绝结果。"""

    decision: PermissionDecision
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PermissionDecision):
            raise TypeError("字段“decision”必须是 PermissionDecision 枚举值。")
        if self.decision is PermissionDecision.ALLOW:
            if self.reason is not None:
                raise ValueError("允许执行的权限结果不能附带拒绝原因。")
            return
        _require_text("reason", self.reason)

    @classmethod
    def allow(cls) -> "PermissionResult":
        """创建允许执行结果。"""

        return cls(decision=PermissionDecision.ALLOW)

    @classmethod
    def deny(cls, reason: str) -> "PermissionResult":
        """创建带明确原因的拒绝结果。"""

        return cls(decision=PermissionDecision.DENY, reason=reason)
