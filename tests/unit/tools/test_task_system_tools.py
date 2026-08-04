from __future__ import annotations

import pytest

from local_dev_agent.tasks import Task, TaskService
from local_dev_agent.tools import ToolCallRequest, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import (
    TaskClaimTool,
    TaskCompleteTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
)
from local_dev_agent.tools.errors import ToolValidationError


class InMemoryTaskRepository:
    """为任务工具测试提供最小的可替换仓储。"""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> tuple[Task, ...]:
        return tuple(self._tasks[task_id] for task_id in sorted(self._tasks))

    def replace(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        return task

    def compare_and_replace(self, *, expected: Task, replacement: Task) -> bool:
        if self._tasks.get(expected.task_id) != expected:
            return False
        self._tasks[replacement.task_id] = replacement
        return True


class SequenceTaskIdGenerator:
    """用稳定任务标识让工具测试可读且可重复。"""

    def __init__(self) -> None:
        self._task_ids = iter(("task-schema", "task-api", "task-tests"))

    def new_task_id(self) -> str:
        return next(self._task_ids)


def _service() -> TaskService:
    return TaskService(InMemoryTaskRepository(), SequenceTaskIdGenerator())


def test_task_system_tools_use_the_required_non_conflicting_names() -> None:
    service = _service()
    tools = (
        TaskCreateTool(service),
        TaskListTool(service),
        TaskGetTool(service),
        TaskClaimTool(service),
        TaskCompleteTool(service),
    )

    assert tuple(tool.definition.name for tool in tools) == (
        "task_create",
        "task_list",
        "task_get",
        "task_claim",
        "task_complete",
    )


def test_task_tools_create_query_claim_complete_and_report_unblocked_tasks() -> None:
    service = _service()
    create = TaskCreateTool(service)
    list_tasks = TaskListTool(service)
    get = TaskGetTool(service)
    claim = TaskClaimTool(service)
    complete = TaskCompleteTool(service)

    schema = create.run({"subject": "建立表结构。"})
    api = create.run(
        {
            "subject": "实现 API。",
            "description": "新增登录端点。",
            "blocked_by": ["task-schema"],
        }
    )

    assert schema["task_id"] == "task-schema"
    assert api["blocked_by"] == ["task-schema"]
    assert [task["task_id"] for task in list_tasks.run({})["tasks"]] == [  # type: ignore[index]
        "task-api",
        "task-schema",
    ]
    assert get.run({"task_id": "task-api"})["description"] == "新增登录端点。"

    claimed_schema = claim.run({"task_id": "task-schema", "owner": "agent-db"})
    completed_schema = complete.run({"task_id": "task-schema"})
    claimed_api = claim.run({"task_id": "task-api", "owner": "agent-api"})

    assert claimed_schema["status"] == "in_progress"
    assert completed_schema["task"]["status"] == "completed"  # type: ignore[index]
    assert completed_schema["unblocked_tasks"] == [  # type: ignore[index]
        {
            "task_id": "task-api",
            "subject": "实现 API。",
            "description": "新增登录端点。",
            "status": "pending",
            "owner": None,
            "blocked_by": ["task-schema"],
        }
    ]
    assert claimed_api["owner"] == "agent-api"


@pytest.mark.parametrize(
    ("tool_factory", "arguments", "message"),
    [
        (TaskCreateTool, {"subject": " "}, "subject”必须是非空字符串"),
        (
            TaskCreateTool,
            {"subject": "任务", "blocked_by": ["", "task-1"]},
            "blocked_by”必须是非空字符串数组",
        ),
        (TaskGetTool, {"task_id": " "}, "task_id”必须是非空字符串"),
        (
            TaskClaimTool,
            {"task_id": "task-1", "owner": " "},
            "owner”必须是非空字符串",
        ),
        (TaskCompleteTool, {"task_id": " "}, "task_id”必须是非空字符串"),
    ],
)
def test_task_tools_reject_invalid_direct_arguments(
    tool_factory: type[object],
    arguments: dict[str, object],
    message: str,
) -> None:
    tool = tool_factory(_service())  # type: ignore[operator]

    with pytest.raises(ToolValidationError, match=message):
        tool.run(arguments)  # type: ignore[attr-defined]


def test_task_tools_reuse_the_standard_executor_validation_boundary() -> None:
    service = _service()
    registry = ToolRegistry()
    registry.register(TaskCreateTool(service))

    result = ToolExecutor(registry).execute(
        ToolCallRequest(
            name="task_create",
            arguments={"subject": "任务", "unexpected": "值"},
        )
    )

    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ToolValidationError"


def test_task_tools_require_the_complete_application_service_port() -> None:
    with pytest.raises(TypeError, match="任务应用服务必须提供"):
        TaskCreateTool(object())  # type: ignore[arg-type]
