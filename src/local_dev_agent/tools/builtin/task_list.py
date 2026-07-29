"""列出跨会话任务图节点的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.tasks import TaskApplicationService

from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext
from .task_application import require_task_application_service
from .task_views import task_to_data


class TaskListTool(Tool):
    """返回当前任务图的稳定摘要快照。"""

    def __init__(self, service: TaskApplicationService) -> None:
        self._service = require_task_application_service(service)
        self._definition = ToolDefinition(
            name="task_list",
            description="列出全部跨会话任务及其状态、负责人和前置依赖。",
            parameters={"type": "object", "properties": {}, "required": []},
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回无需参数的任务列表工具定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """返回每项任务的 JSON 原生快照，不解释或改变任务状态。"""

        return {"tasks": [task_to_data(task) for task in self._service.list_tasks()]}
