from __future__ import annotations

from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import CronTask
from local_dev_agent.hooks import HookDecision, HookEvent, HookRegistry, HookResult, HookRunner
from local_dev_agent.tools import ToolCallRequest, ToolExecutionContext, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import CancelCronTool, ListCronsTool, ScheduleCronTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


class RecordingCronService:
    """记录工具输入，验证工具不自行管理仓储或 Session。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.task = CronTask.create(
            task_id="cron-001",
            cron="0 9 * * *",
            prompt="运行检查。",
            owner_session_id="session-001",
            created_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc),
        )

    def schedule(self, **kwargs: object) -> CronTask:
        self.calls.append(("schedule", kwargs))
        return self.task

    def list_for_session(self, *, session_id: str) -> tuple[CronTask, ...]:
        self.calls.append(("list", session_id))
        return (self.task,)

    def cancel(self, *, session_id: str, task_id: str) -> CronTask:
        self.calls.append(("cancel", (session_id, task_id)))
        return self.task


class BlockingHook:
    name = "block-cron"

    def handle(self, context):
        return HookResult(decision=HookDecision.BLOCK, message="测试阻止。")


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(session_id="session-001", run_id="run-001", step_id="step-001")


def test_cron_tools_use_context_session_and_return_structured_snapshots() -> None:
    service = RecordingCronService()
    scheduled = ScheduleCronTool(service).run({"cron": "0 9 * * *", "prompt": "运行检查。", "durable": True}, context=_context())
    listed = ListCronsTool(service).run({}, context=_context())
    cancelled = CancelCronTool(service).run({"task_id": "cron-001"}, context=_context())

    assert scheduled["task_id"] == "cron-001"
    assert listed["tasks"][0]["durable"] is False
    assert cancelled["cron"] == "0 9 * * *"
    assert service.calls[0][1]["session_id"] == "session-001"  # type: ignore[index]
    assert service.calls[2] == ("cancel", ("session-001", "cron-001"))


def test_cron_tools_reject_missing_context_and_invalid_arguments() -> None:
    service = RecordingCronService()
    with pytest.raises(ToolExecutionError, match="执行上下文"):
        ListCronsTool(service).run({})
    with pytest.raises(ToolValidationError, match="非空字符串"):
        ScheduleCronTool(service).run({"cron": " ", "prompt": "任务。"}, context=_context())
    with pytest.raises(ToolValidationError, match="task_id"):
        CancelCronTool(service).run({}, context=_context())


def test_standard_hook_blocks_cron_registration_before_service_is_called() -> None:
    service = RecordingCronService()
    registry = ToolRegistry()
    registry.register(ScheduleCronTool(service))
    hooks = HookRegistry()
    hooks.register(HookEvent.PRE_TOOL_USE, BlockingHook())

    result = ToolExecutor(registry, hook_runner=HookRunner(hooks)).execute(
        ToolCallRequest(name="schedule_cron", arguments={"cron": "0 9 * * *", "prompt": "运行检查。"}),
        context=_context(),
    )

    assert result.success is False
    assert result.error is not None and result.error["type"] == "ToolHookBlockedError"
    assert service.calls == []
