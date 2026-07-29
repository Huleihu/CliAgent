"""认领跨会话任务的内置工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.tasks import TaskApplicationService

from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext
from .task_application import require_task_application_service
from .task_create import _read_nonempty_text
from .task_views import task_to_data


class TaskClaimTool(Tool):
    """认领任务；依赖和状态检查始终由应用服务与领域规则执行。"""

    def __init__(self, service: TaskApplicationService) -> None:
        self._service = require_task_application_service(service)
        self._definition = ToolDefinition(
            name="task_claim",
            description="认领尚未被阻塞的待认领任务，并记录负责人。",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "需要认领的任务标识。",
                    },
                    "owner": {
                        "type": "string",
                        "description": "认领该任务的执行者标识。",
                    },
                },
                "required": ["task_id", "owner"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回认领任务所需的任务和负责人参数协议。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """请求应用服务完成依赖检查、状态转换和持久化。"""

        return task_to_data(
            self._service.claim_task(
                task_id=_read_nonempty_text(arguments, "task_id"),
                owner=_read_nonempty_text(arguments, "owner"),
            )
        )
