from datetime import datetime, timezone

import pytest

from local_dev_agent.tools import ToolCallRequest, ToolExecutionContext, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import CreateWorktreeTool, KeepWorktreeTool, RemoveWorktreeTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError
from local_dev_agent.worktrees import (
    Worktree,
    WorktreeEventType,
    WorktreeLifecycleEvent,
    WorktreeOperationResult,
)


class RecordingWorktreeService:
    """记录 Lead 工具传入的参数，不执行真实 Git 生命周期。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @staticmethod
    def _result(
        event_type: WorktreeEventType,
        operation_id: str,
        task_id: str | None,
    ) -> WorktreeOperationResult:
        return WorktreeOperationResult(
            event=WorktreeLifecycleEvent(
                event_type=event_type,
                operation_id=operation_id,
                worktree=Worktree(
                    name="api-login",
                    directory=".worktrees/api-login",
                    branch="wt/api-login",
                    base_commit="abc123",
                ),
                task_id=task_id,
                occurred_at=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            )
        )

    def create_worktree(self, **kwargs: object) -> WorktreeOperationResult:
        self.calls.append(("create_worktree", kwargs))
        return self._result(
            WorktreeEventType.CREATE,
            str(kwargs["operation_id"]),
            kwargs["task_id"],  # type: ignore[arg-type]
        )

    def remove_worktree(self, **kwargs: object) -> WorktreeOperationResult:
        self.calls.append(("remove_worktree", kwargs))
        return self._result(WorktreeEventType.REMOVE, str(kwargs["operation_id"]), None)

    def keep_worktree(self, **kwargs: object) -> WorktreeOperationResult:
        self.calls.append(("keep_worktree", kwargs))
        return self._result(WorktreeEventType.KEEP, str(kwargs["operation_id"]), None)


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="session-lead",
        run_id="run-001",
        step_id="step-001",
        call_id="call-001",
    )


def test_worktree_tools_use_stable_lead_visible_names() -> None:
    service = RecordingWorktreeService()

    assert tuple(
        tool.definition.name
        for tool in (
            CreateWorktreeTool(service),
            RemoveWorktreeTool(service),
            KeepWorktreeTool(service),
        )
    ) == ("create_worktree", "remove_worktree", "keep_worktree")


def test_worktree_tools_forward_context_derived_operation_ids_and_json_results() -> None:
    service = RecordingWorktreeService()
    create = CreateWorktreeTool(service)
    remove = RemoveWorktreeTool(service)
    keep = KeepWorktreeTool(service)

    created = create.run({"name": "api-login", "task_id": "task-api"}, context=_context())
    removed = remove.run({"name": "api-login", "discard_changes": True}, context=_context())
    kept = keep.run({"name": "api-login"}, context=_context())

    assert created["operation_id"] == "worktree-create-call-001"
    assert created["task_id"] == "task-api"
    assert created["worktree"]["base_commit"] == "abc123"  # type: ignore[index]
    assert removed["event_type"] == "remove"
    assert kept["event_type"] == "keep"
    assert service.calls[0][1]["task_id"] == "task-api"
    assert service.calls[1][1]["discard_changes"] is True


def test_worktree_tools_use_standard_executor_validation_and_require_context() -> None:
    service = RecordingWorktreeService()
    registry = ToolRegistry()
    registry.register(CreateWorktreeTool(service))
    executor = ToolExecutor(registry)

    invalid = executor.execute(
        ToolCallRequest(name="create_worktree", arguments={"name": "api-login", "extra": 1}),
        context=_context(),
    )
    missing_context = executor.execute(
        ToolCallRequest(name="create_worktree", arguments={"name": "api-login"})
    )

    assert invalid.success is False
    assert invalid.error is not None
    assert invalid.error["type"] == "ToolValidationError"
    assert missing_context.success is False
    assert missing_context.error is not None
    assert missing_context.error["type"] == "ToolExecutionError"
    with pytest.raises(ToolValidationError, match="discard_changes"):
        RemoveWorktreeTool(service).run(
            {"name": "api-login", "discard_changes": "true"},
            context=_context(),
        )
    with pytest.raises(ToolExecutionError, match="ToolExecutionContext"):
        KeepWorktreeTool(service).run({"name": "api-login"})
    with pytest.raises(TypeError, match="完整的工作树应用服务"):
        CreateWorktreeTool(object())  # type: ignore[arg-type]
