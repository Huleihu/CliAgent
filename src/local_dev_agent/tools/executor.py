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
from .schema import ToolCallRequest, ToolCallResult

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
        pre_tool_context: PreToolUseContext | None = None,
    ) -> ToolCallResult:
        """执行一次调用；启用 Hook 时必须在工具运行前提供关联上下文。"""

        started_at = perf_counter()
        try:
            tool = self._registry.get(request.name)
            validate_arguments(
                tool_name=request.name,
                parameters=tool.definition.parameters,
                arguments=request.arguments,
            )
            self._trigger_pre_tool_use(request, pre_tool_context)
        except (
            HookExecutionError,
            ToolNotFoundError,
            ToolValidationError,
            ToolExecutionError,
            TypeError,
        ) as error:
            return self._failed_result(request, error, started_at)

        result = self._run_tool(request, tool, started_at)
        self._trigger_post_tool_use(pre_tool_context, result)
        return result

    def _run_tool(
        self,
        request: ToolCallRequest,
        tool: object,
        started_at: float,
    ) -> ToolCallResult:
        """运行已通过执行前检查的工具，并将运行期失败收束为结果。"""

        try:
            data = tool.run(request.arguments)  # type: ignore[attr-defined]
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

    def _trigger_pre_tool_use(
        self,
        request: ToolCallRequest,
        pre_tool_context: PreToolUseContext | None,
    ) -> None:
        """在已校验调用进入工具实现前触发 Hook，拒绝缺失或错配上下文。"""

        if self._hook_runner is None:
            return
        if pre_tool_context is None:
            raise ToolExecutionError("启用 HookRunner 后必须提供 PreToolUseContext。")
        if pre_tool_context.request != request:
            raise ToolExecutionError("PreToolUseContext 必须关联当前工具调用请求。")
        result = self._hook_runner.trigger(HookEvent.PRE_TOOL_USE, pre_tool_context)
        if result.decision is HookDecision.BLOCK:
            raise ToolHookBlockedError(result.message or "执行前 Hook 未提供阻止原因。")

    def _trigger_post_tool_use(
        self,
        pre_tool_context: PreToolUseContext | None,
        result: ToolCallResult,
    ) -> None:
        """在工具结果确定后触发观察型 Hook，不允许其改写既有结果。"""

        if self._hook_runner is None or pre_tool_context is None:
            return
        post_tool_context = PostToolUseContext(
            session_id=pre_tool_context.session_id,
            run_id=pre_tool_context.run_id,
            step_id=pre_tool_context.step_id,
            request=pre_tool_context.request,
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
