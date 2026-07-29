"""完成跨会话任务的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.tasks import TaskApplicationService

from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext
from .task_application import require_task_application_service
from .task_create import _read_nonempty_text
from .task_views import task_to_data


class TaskCompleteTool(Tool):
    """完成已认领任务，并向模型报告本次新解锁的下游任务。"""

    def __init__(self, service: TaskApplicationService) -> None:
        self._service = require_task_application_service(service)
        self._definition = ToolDefinition(
            name="task_complete",
            description="完成已认领任务，并返回刚刚解除依赖阻塞的下游任务。",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "需要完成的任务标识。",
                    }
                },
                "required": ["task_id"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回完成任务所需的标识参数协议。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """完成任务，并将完成任务和新解锁任务一并回填模型。"""

        completion = self._service.complete_task(
            task_id=_read_nonempty_text(arguments, "task_id")
        )
        return {
            "task": task_to_data(completion.task),
            "unblocked_tasks": [
                task_to_data(task) for task in completion.unblocked_tasks
            ],
        }
