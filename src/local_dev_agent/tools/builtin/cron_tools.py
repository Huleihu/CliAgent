"""父 Agent 使用的 Cron 注册、查询与取消工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.cron import CronTask, CronTaskApplicationService, CronTaskScope

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


def _service(value: CronTaskApplicationService) -> CronTaskApplicationService:
    if not all(callable(getattr(value, name, None)) for name in ("schedule", "list_for_session", "cancel")):
        raise TypeError("service 必须提供 CronTaskApplicationService 的全部方法。")
    return value


def _context(value: ToolExecutionContext | None) -> ToolExecutionContext:
    if value is None:
        raise ToolExecutionError("Cron 工具必须在带 Session 的执行上下文中调用。")
    return value


def _data(task: CronTask) -> dict[str, object]:
    return {"task_id": task.task_id, "cron": task.cron, "prompt": task.prompt, "recurring": task.recurring, "durable": task.scope is CronTaskScope.DURABLE}


class ScheduleCronTool(Tool):
    """注册一项由 Scheduler 在未来入队的 cron 定义。"""

    def __init__(self, service: CronTaskApplicationService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(name="schedule_cron", description="创建五段式定时任务。", parameters={"type": "object", "properties": {"cron": {"type": "string"}, "prompt": {"type": "string"}, "recurring": {"type": "boolean"}, "durable": {"type": "boolean"}}, "required": ["cron", "prompt"]}, tags=("state",))

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(self, arguments: Mapping[str, object], *, context: ToolExecutionContext | None = None) -> Mapping[str, object]:
        cron, prompt = arguments.get("cron"), arguments.get("prompt")
        if not isinstance(cron, str) or not cron.strip() or not isinstance(prompt, str) or not prompt.strip():
            raise ToolValidationError("字段“cron”和“prompt”必须是非空字符串。")
        recurring, durable = arguments.get("recurring", True), arguments.get("durable", False)
        if not isinstance(recurring, bool) or not isinstance(durable, bool):
            raise ToolValidationError("字段“recurring”和“durable”必须是布尔值。")
        return _data(self._service.schedule(session_id=_context(context).session_id, cron=cron, prompt=prompt, recurring=recurring, durable=durable))


class ListCronsTool(Tool):
    """列出当前父 Session 可见的定时定义。"""

    def __init__(self, service: CronTaskApplicationService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(name="list_crons", description="列出当前会话可见的定时任务。", parameters={"type": "object", "properties": {}, "required": []}, tags=("state",))

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(self, arguments: Mapping[str, object], *, context: ToolExecutionContext | None = None) -> Mapping[str, object]:
        return {"tasks": [_data(task) for task in self._service.list_for_session(session_id=_context(context).session_id)]}


class CancelCronTool(Tool):
    """取消当前父 Session 可访问的 cron 定义。"""

    def __init__(self, service: CronTaskApplicationService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(name="cancel_cron", description="取消当前会话可访问的定时任务。", parameters={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}, tags=("state",))

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(self, arguments: Mapping[str, object], *, context: ToolExecutionContext | None = None) -> Mapping[str, object]:
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ToolValidationError("字段“task_id”必须是非空字符串。")
        return _data(self._service.cancel(session_id=_context(context).session_id, task_id=task_id))
