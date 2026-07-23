"""工具调用的安全执行边界。"""

from time import perf_counter

from .errors import ToolExecutionError, ToolNotFoundError, ToolValidationError
from .registry import ToolRegistry
from .schema import ToolCallRequest, ToolCallResult


class ToolExecutor:
    """统一处理工具查找、轻量校验、异常收束和耗时记录。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, request: ToolCallRequest) -> ToolCallResult:
        """执行一次调用；预期失败转换为结果，避免异常进入 Agent Loop。"""

        started_at = perf_counter()
        try:
            tool = self._registry.get(request.name)
            self._validate_required_arguments(tool.definition.parameters, request)
            data = tool.run(request.arguments)
            return ToolCallResult.succeeded(
                name=request.name,
                data=data,
                duration_ms=self._elapsed_ms(started_at),
                call_id=request.call_id,
            )
        except (ToolNotFoundError, ToolValidationError, ToolExecutionError, TypeError) as error:
            return self._failed_result(request, error, started_at)
        except Exception as error:
            return self._failed_result(
                request,
                ToolExecutionError(f"工具执行失败：{error}"),
                started_at,
            )

    def _validate_required_arguments(self, parameters, request: ToolCallRequest) -> None:
        required_fields = parameters.get("required", [])
        missing_fields = sorted(
            field_name for field_name in required_fields if field_name not in request.arguments
        )
        if missing_fields:
            raise ToolValidationError(
                f"工具“{request.name}”缺少必填参数：{', '.join(missing_fields)}。"
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
