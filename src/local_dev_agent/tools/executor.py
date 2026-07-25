"""工具调用的安全执行边界。"""

import logging
from time import perf_counter

from local_dev_agent.hooks import (
    HookDecision,
    HookExecutionError,
    HookEvent,
    HookRunner,
    PostToolUseContext,
    PreToolUseContext,
)

from .argument_validator import validate_arguments
from .errors import (
    ToolExecutionError,
    ToolHookBlockedError,
    ToolNotFoundError,
    ToolValidationError,
)
from .registry import ToolRegistry
from .schema import ToolCallRequest, ToolCallResult, ToolExecutionContext

logger = logging.getLogger(__name__)


class ToolExecutor:
    """统一处理工具查找、校验、执行前 Hook、异常收束和耗时记录。"""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        hook_runner: HookRunner | None = None,
    ) -> None:
        self._registry = registry
        self._hook_runner = hook_runner

    def execute(
        self,
        request: ToolCallRequest,
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolCallResult:
        """执行一次调用；上下文存在时统一传给工具并派生 Hook 关联。"""

        started_at = perf_counter()
        try:
            tool = self._registry.get(request.name)
            validate_arguments(
                tool_name=request.name,
                parameters=tool.definition.parameters,
                arguments=request.arguments,
            )
            self._validate_execution_context(request, context)
            self._trigger_pre_tool_use(request, context)
        except (
            HookExecutionError,
            ToolNotFoundError,
            ToolValidationError,
            ToolExecutionError,
            TypeError,
        ) as error:
            return self._failed_result(request, error, started_at)

        result = self._run_tool(request, tool, context, started_at)
        self._trigger_post_tool_use(request, context, result)
        return result

    def _run_tool(
        self,
        request: ToolCallRequest,
        tool: object,
        context: ToolExecutionContext | None,
        started_at: float,
    ) -> ToolCallResult:
        """运行已通过执行前检查的工具，并将运行期失败收束为结果。"""

        try:
            data = tool.run(  # type: ignore[attr-defined]
                request.arguments,
                context=context,
            )
            return ToolCallResult.succeeded(
                name=request.name,
                data=data,
                duration_ms=self._elapsed_ms(started_at),
                call_id=request.call_id,
            )
        except (ToolValidationError, ToolExecutionError, TypeError) as error:
            return self._failed_result(request, error, started_at)
        except Exception as error:
            return self._failed_result(
                request,
                ToolExecutionError(f"工具执行失败：{error}"),
                started_at,
            )

    def _validate_execution_context(
        self,
        request: ToolCallRequest,
        context: ToolExecutionContext | None,
    ) -> None:
        """拒绝缺失的 Hook 关联和与当前请求不一致的调用标识。"""

        if self._hook_runner is not None and context is None:
            raise ToolExecutionError("启用 HookRunner 后必须提供 ToolExecutionContext。")
        if context is not None and context.call_id != request.call_id:
            raise ToolExecutionError("ToolExecutionContext 必须关联当前工具调用请求。")

    def _trigger_pre_tool_use(
        self,
        request: ToolCallRequest,
        context: ToolExecutionContext | None,
    ) -> None:
        """从统一执行上下文派生执行前 Hook 关联。"""

        if self._hook_runner is None:
            return
        if context is None:
            raise AssertionError("执行上下文已在触发 Hook 前完成校验。")
        pre_tool_context = PreToolUseContext(
            session_id=context.session_id,
            run_id=context.run_id,
            step_id=context.step_id,
            request=request,
        )
        result = self._hook_runner.trigger(HookEvent.PRE_TOOL_USE, pre_tool_context)
        if result.decision is HookDecision.BLOCK:
            raise ToolHookBlockedError(result.message or "执行前 Hook 未提供阻止原因。")

    def _trigger_post_tool_use(
        self,
        request: ToolCallRequest,
        context: ToolExecutionContext | None,
        result: ToolCallResult,
    ) -> None:
        """在工具结果确定后触发观察型 Hook，不允许其改写既有结果。"""

        if self._hook_runner is None or context is None:
            return
        post_tool_context = PostToolUseContext(
            session_id=context.session_id,
            run_id=context.run_id,
            step_id=context.step_id,
            request=request,
            result=result,
        )
        try:
            self._hook_runner.trigger(HookEvent.POST_TOOL_USE, post_tool_context)
        except HookExecutionError:
            logger.warning(
                "工具执行后 Hook 失败，不影响工具结果。",
                exc_info=True,
                extra={
                    "session_id": post_tool_context.session_id,
                    "run_id": post_tool_context.run_id,
                    "step_id": post_tool_context.step_id,
                },
            )

    def _failed_result(self, request: ToolCallRequest, error: Exception, started_at: float) -> ToolCallResult:
        return ToolCallResult.failed(
            name=request.name,
            error=error,
            duration_ms=self._elapsed_ms(started_at),
            call_id=request.call_id,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return (perf_counter() - started_at) * 1000
