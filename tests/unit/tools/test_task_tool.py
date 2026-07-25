from __future__ import annotations

import pytest

from local_dev_agent.subagents import SubagentOutcome, SubagentResult, SubagentTask
from local_dev_agent.tools import (
    DELEGATION_TOOL_TAG,
    ToolCallRequest,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)
from local_dev_agent.tools.builtin import TaskTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


class RecordingSubagentRunner:
    """记录委派任务并返回预设结果。"""

    def __init__(self, result: SubagentResult) -> None:
        self._result = result
        self.tasks: list[SubagentTask] = []

    def run(self, task: SubagentTask) -> SubagentResult:
        """保存任务，模拟同步子 Agent 完成。"""

        self.tasks.append(task)
        return SubagentResult.create(
            task_id=task.task_id,
            outcome=self._result.outcome,
            summary=self._result.summary,
            child_session_id=self._result.child_session_id,
            child_run_id=self._result.child_run_id,
            evidence=self._result.evidence,
            artifacts=self._result.artifacts,
            unresolved_risks=self._result.unresolved_risks,
        )


def _runner(*, outcome: SubagentOutcome = SubagentOutcome.SUCCEEDED) -> RecordingSubagentRunner:
    return RecordingSubagentRunner(
        SubagentResult.create(
            task_id="placeholder",
            outcome=outcome,
            summary="子任务结论。",
            child_session_id="session-child",
            child_run_id="run-child",
            evidence=("已读取 pyproject.toml。",),
            artifacts=("reports/result.md",),
            unresolved_risks=("未运行集成测试。",),
        )
    )


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="session-parent",
        run_id="run-parent",
        step_id="step-parent",
        call_id="toolu-parent",
    )


def test_task_tool_builds_a_task_from_execution_context_and_serializes_result() -> None:
    runner = _runner()
    tool = TaskTool(runner)

    result = tool.run(
        {
            "description": "调查测试框架。",
            "acceptance_criteria": ["返回框架名称", "说明证据"],
        },
        context=_context(),
    )

    task = runner.tasks[0]
    assert task.parent_session_id == "session-parent"
    assert task.parent_run_id == "run-parent"
    assert task.parent_step_id == "step-parent"
    assert task.description == "调查测试框架。"
    assert task.acceptance_criteria == ("返回框架名称", "说明证据")
    assert result == {
        "task_id": task.task_id,
        "outcome": "succeeded",
        "summary": "子任务结论。",
        "child_session_id": "session-child",
        "child_run_id": "run-child",
        "evidence": ["已读取 pyproject.toml。"],
        "artifacts": ["reports/result.md"],
        "unresolved_risks": ["未运行集成测试。"],
    }


def test_task_tool_declaration_is_tagged_as_delegation_and_accepts_optional_criteria() -> None:
    tool = TaskTool(_runner(outcome=SubagentOutcome.EXHAUSTED))

    result = tool.run({"description": "调查测试框架。"}, context=_context())

    assert tool.definition.tags == (DELEGATION_TOOL_TAG,)
    assert tool.definition.parameters["required"] == ["description"]
    assert result["outcome"] == "exhausted"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "description”必须是非空字符串"),
        ({"description": " "}, "description”必须是非空字符串"),
        ({"description": "任务", "acceptance_criteria": "标准"}, "acceptance_criteria”必须是非空字符串数组"),
        ({"description": "任务", "acceptance_criteria": ["", "标准"]}, "acceptance_criteria”必须是非空字符串数组"),
    ],
)
def test_task_tool_rejects_invalid_task_data(
    arguments: dict[str, object],
    message: str,
) -> None:
    runner = _runner()

    with pytest.raises(ToolValidationError, match=message):
        TaskTool(runner).run(arguments, context=_context())

    assert runner.tasks == []


def test_task_tool_requires_execution_context_and_runner_port() -> None:
    runner = _runner()

    with pytest.raises(ToolExecutionError, match="ToolExecutionContext"):
        TaskTool(runner).run({"description": "任务"})
    with pytest.raises(TypeError, match="run 方法"):
        TaskTool(object())  # type: ignore[arg-type]


def test_executor_returns_structured_failure_before_runner_for_invalid_task_arguments() -> None:
    runner = _runner()
    tool = TaskTool(runner)
    registry = ToolRegistry()
    registry.register(tool)
    request = ToolCallRequest(
        name="task",
        arguments={"description": "任务", "acceptance_criteria": [1]},
        call_id="toolu-parent",
    )

    result = ToolExecutor(registry).execute(request, context=_context())

    assert result.success is False
    assert result.error is not None and result.error["type"] == "ToolValidationError"
    assert runner.tasks == []
