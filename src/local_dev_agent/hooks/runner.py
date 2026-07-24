"""按注册顺序执行 Hook 并收束回调失败。"""

from .errors import HookExecutionError, HookValidationError
from .ports import Hook, HookContext
from .registry import HookRegistry
from .schema import HookDecision, HookEvent, HookResult


class HookRunner:
    """触发指定事件的 Hook，首个阻止结果终止该事件的后续回调。"""

    def __init__(self, registry: HookRegistry) -> None:
        if not isinstance(registry, HookRegistry):
            raise TypeError("HookRunner 必须使用 HookRegistry。")
        self._registry = registry

    def trigger(self, event: HookEvent, context: HookContext) -> HookResult:
        """触发事件并返回首个阻止结果或默认继续结果。"""

        self._validate_context(event, context)
        for hook in self._registry.list_hooks(event):
            result = self._run_hook(event, hook.name, hook, context)
            if result.decision is HookDecision.BLOCK:
                return result
        return HookResult.continue_()

    @staticmethod
    def _validate_context(event: HookEvent, context: HookContext) -> None:
        if not isinstance(event, HookEvent):
            raise HookValidationError("事件必须是 HookEvent 枚举值。")
        expected_context_type = {
            HookEvent.USER_PROMPT_SUBMIT: "UserPromptSubmitContext",
            HookEvent.PRE_TOOL_USE: "PreToolUseContext",
            HookEvent.POST_TOOL_USE: "PostToolUseContext",
            HookEvent.STOP: "StopContext",
        }[event]
        if getattr(context, "event", None) is not event:
            raise HookValidationError(
                f"事件“{event.value}”必须使用“{expected_context_type}”。"
            )

    @staticmethod
    def _run_hook(
        event: HookEvent,
        hook_name: str,
        hook: Hook,
        context: HookContext,
    ) -> HookResult:
        try:
            result = hook.handle(context)
        except Exception as error:
            raise HookExecutionError(
                event=event.value,
                hook_name=hook_name,
                reason="回调抛出异常",
            ) from error
        if not isinstance(result, HookResult):
            raise HookExecutionError(
                event=event.value,
                hook_name=hook_name,
                reason="回调未返回 HookResult",
            )
        return result
