"""仅供 Lead 创建、保留和删除受控 Git 工作树的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.worktrees import WorktreeApplicationService, WorktreeOperationResult

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


def _service(value: object) -> WorktreeApplicationService:
    """确保工具只依赖工作树应用用例，不接触 Git 或 JSONL 适配器。"""

    method_names = ("create_worktree", "remove_worktree", "keep_worktree")
    if not all(callable(getattr(value, method_name, None)) for method_name in method_names):
        raise TypeError("工作树工具必须提供完整的工作树应用服务。")
    return value  # type: ignore[return-value]


def _context(value: ToolExecutionContext | None) -> ToolExecutionContext:
    """要求稳定调用标识，使模型重放不会重复创建或删除工作树。"""

    if value is None:
        raise ToolExecutionError("工作树工具必须在 ToolExecutionContext 中执行。")
    return value


def _text(arguments: Mapping[str, object], field_name: str) -> str:
    """读取必填非空字符串字段。"""

    value = arguments.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")
    return value


def _optional_text(arguments: Mapping[str, object], field_name: str) -> str | None:
    """读取可省略的非空字符串字段，显式空白仍视为无效。"""

    if field_name not in arguments:
        return None
    return _text(arguments, field_name)


def _optional_bool(arguments: Mapping[str, object], field_name: str) -> bool:
    """读取可省略布尔字段，缺省时保持安全删除默认值。"""

    value = arguments.get(field_name, False)
    if not isinstance(value, bool):
        raise ToolValidationError(f"字段“{field_name}”必须是布尔值。")
    return value


def _operation_id(context: ToolExecutionContext, *, action: str) -> str:
    """将本次工具调用关联为工作树领域稳定幂等键。"""

    return f"worktree-{action}-{context.call_id or context.step_id}"


def _result_data(result: WorktreeOperationResult) -> dict[str, object]:
    """把领域结果转换为仅包含 JSON 原生值的工具响应。"""

    event = result.event
    return {
        "event_type": event.event_type.value,
        "operation_id": event.operation_id,
        "task_id": event.task_id,
        "worktree": {
            "name": event.worktree.name,
            "directory": event.worktree.directory,
            "branch": event.worktree.branch,
            "base_commit": event.worktree.base_commit,
        },
        "replayed": result.replayed,
    }


class CreateWorktreeTool(Tool):
    """创建独立 Git 工作树，并可选地绑定 S12 任务。"""

    def __init__(self, service: WorktreeApplicationService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(
            name="create_worktree",
            description="创建独立 Git 工作树与受控分支，并可选地绑定一个任务。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "task_id": {"type": "string"},
                },
                "required": ["name"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        result = self._service.create_worktree(
            name=_text(arguments, "name"),
            task_id=_optional_text(arguments, "task_id"),
            operation_id=_operation_id(execution_context, action="create"),
        )
        return _result_data(result)


class RemoveWorktreeTool(Tool):
    """默认安全删除工作树，仅显式确认后放弃改动。"""

    def __init__(self, service: WorktreeApplicationService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(
            name="remove_worktree",
            description="删除工作树；存在本地或未推送改动时必须显式确认放弃。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "discard_changes": {"type": "boolean"},
                },
                "required": ["name"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        result = self._service.remove_worktree(
            name=_text(arguments, "name"),
            discard_changes=_optional_bool(arguments, "discard_changes"),
            operation_id=_operation_id(execution_context, action="remove"),
        )
        return _result_data(result)


class KeepWorktreeTool(Tool):
    """记录 Lead 保留工作树供后续人工评审的决定。"""

    def __init__(self, service: WorktreeApplicationService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(
            name="keep_worktree",
            description="保留已有工作树和分支，供人工检查或后续合并。",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        result = self._service.keep_worktree(
            name=_text(arguments, "name"),
            operation_id=_operation_id(execution_context, action="keep"),
        )
        return _result_data(result)
