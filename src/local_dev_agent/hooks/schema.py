"""Hook 事件、不可变上下文与控制结果契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from local_dev_agent.models.ports import ModelResponse
from local_dev_agent.tools.schema import ToolCallRequest, ToolCallResult

from .errors import HookValidationError


def _require_text(field_name: str, value: str) -> None:
    """拒绝空关联标识和空文本，避免 Hook 收到无法追溯的上下文。"""

    if not isinstance(value, str) or not value.strip():
        raise HookValidationError(f"字段“{field_name}”必须是非空字符串。")


class HookEvent(StrEnum):
    """Agent 生命周期中可被 Hook 订阅的稳定事件。"""

    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"


class HookDecision(StrEnum):
    """当前 Hook 对默认流程作出的控制决定。"""

    CONTINUE = "continue"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class UserPromptSubmitContext:
    """用户输入已接收、首次模型调用前的不可变 Hook 上下文。"""

    session_id: str
    run_id: str
    step_id: str
    prompt: str

    def __post_init__(self) -> None:
        """确保 Hook 能将输入事件关联到确定的运行与步骤。"""

        _require_text("session_id", self.session_id)
        _require_text("run_id", self.run_id)
        _require_text("step_id", self.step_id)
        _require_text("prompt", self.prompt)


@dataclass(frozen=True, slots=True)
class PreToolUseContext:
    """工具参数校验通过、实际执行前的不可变 Hook 上下文。"""

    session_id: str
    run_id: str
    step_id: str
    request: ToolCallRequest

    def __post_init__(self) -> None:
        """确保执行前 Hook 只接收有效的工具调用契约。"""

        _require_text("session_id", self.session_id)
        _require_text("run_id", self.run_id)
        _require_text("step_id", self.step_id)
        if not isinstance(self.request, ToolCallRequest):
            raise HookValidationError("字段“request”必须是 ToolCallRequest 对象。")


@dataclass(frozen=True, slots=True)
class PostToolUseContext:
    """工具执行结束、结果已收束后的不可变 Hook 上下文。"""

    session_id: str
    run_id: str
    step_id: str
    request: ToolCallRequest
    result: ToolCallResult

    def __post_init__(self) -> None:
        """确保执行后 Hook 可同时读取调用快照和结构化结果。"""

        _require_text("session_id", self.session_id)
        _require_text("run_id", self.run_id)
        _require_text("step_id", self.step_id)
        if not isinstance(self.request, ToolCallRequest):
            raise HookValidationError("字段“request”必须是 ToolCallRequest 对象。")
        if not isinstance(self.result, ToolCallResult):
            raise HookValidationError("字段“result”必须是 ToolCallResult 对象。")


@dataclass(frozen=True, slots=True)
class StopContext:
    """模型给出最终响应、运行完成前的不可变 Hook 上下文。"""

    session_id: str
    run_id: str
    step_id: str
    response: ModelResponse

    def __post_init__(self) -> None:
        """确保停止 Hook 能读取可回溯的最终模型响应。"""

        _require_text("session_id", self.session_id)
        _require_text("run_id", self.run_id)
        _require_text("step_id", self.step_id)
        if not isinstance(self.response, ModelResponse):
            raise HookValidationError("字段“response”必须是 ModelResponse 对象。")


@dataclass(frozen=True, slots=True)
class HookResult:
    """Hook 对当前默认流程作出的结构化控制结果。"""

    decision: HookDecision
    message: str | None = None

    def __post_init__(self) -> None:
        """限制继续与阻止结果的消息语义，避免调用方自行猜测。"""

        if not isinstance(self.decision, HookDecision):
            raise HookValidationError("字段“decision”必须是 HookDecision 枚举值。")
        if self.decision is HookDecision.CONTINUE:
            if self.message is not None:
                raise HookValidationError("继续执行的 Hook 结果不能附带消息。")
            return
        _require_text("message", self.message)

    @classmethod
    def continue_(cls) -> "HookResult":
        """创建不改变默认流程的 Hook 结果。"""

        return cls(decision=HookDecision.CONTINUE)

    @classmethod
    def block(cls, message: str) -> "HookResult":
        """创建阻止当前默认流程并说明原因的 Hook 结果。"""

        return cls(decision=HookDecision.BLOCK, message=message)
