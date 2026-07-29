"""读取单个跨会话任务详情的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.tasks import TaskApplicationService

from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext
from .task_application import require_task_application_service
from .task_create import _read_nonempty_text
from .task_views import task_to_data


class TaskGetTool(Tool):
    """按稳定标识返回一个任务的完整描述与当前状态。"""

    def __init__(self, service: TaskApplicationService) -> None:
        self._service = require_task_application_service(service)
        self._definition = ToolDefinition(
            name="task_get",
            description="读取指定跨会话任务的完整说明、状态、负责人和依赖。",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "需要读取的任务标识。",
                    }
                },
                "required": ["task_id"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回读取任务详情所需的标识参数协议。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """按标识查询任务，并以 JSON 原生对象返回。"""

        return task_to_data(self._service.get_task(_read_nonempty_text(arguments, "task_id")))
