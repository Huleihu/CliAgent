"""创建跨会话任务图节点的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.tasks import TaskApplicationService

from ..errors import ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext
from .task_application import require_task_application_service
from .task_views import task_to_data


class TaskCreateTool(Tool):
    """将模型参数转换为创建任务应用用例，不管理标识或持久化。"""

    def __init__(self, service: TaskApplicationService) -> None:
        self._service = require_task_application_service(service)
        self._definition = ToolDefinition(
            name="task_create",
            description="创建可跨会话恢复的任务，可声明其前置依赖任务。",
            parameters={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "任务的简短标题。",
                    },
                    "description": {
                        "type": "string",
                        "description": "可选的完整任务说明。",
                    },
                    "blocked_by": {
                        "type": "array",
                        "description": "可选的前置任务标识列表。",
                        "items": {"type": "string"},
                    },
                },
                "required": ["subject"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回创建任务所需的最小模型参数协议。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """校验任务文本与依赖标识后，返回已持久化的新任务快照。"""

        task = self._service.create_task(
            subject=_read_nonempty_text(arguments, "subject"),
            description=_read_optional_text(arguments, "description"),
            blocked_by=_read_optional_string_array(arguments, "blocked_by"),
        )
        return task_to_data(task)


def _read_nonempty_text(arguments: Mapping[str, object], field_name: str) -> str:
    """读取工具协议中必须提供的非空文本。"""

    value = arguments.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")
    return value


def _read_optional_text(arguments: Mapping[str, object], field_name: str) -> str:
    """读取允许为空的可选说明文本。"""

    value = arguments.get(field_name, "")
    if not isinstance(value, str):
        raise ToolValidationError(f"字段“{field_name}”必须是字符串。")
    return value


def _read_optional_string_array(
    arguments: Mapping[str, object],
    field_name: str,
) -> tuple[str, ...]:
    """读取可选依赖标识数组，并冻结为应用服务输入快照。"""

    value = arguments.get(field_name, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ToolValidationError(f"字段“{field_name}”必须是非空字符串数组。")
    return tuple(value)
