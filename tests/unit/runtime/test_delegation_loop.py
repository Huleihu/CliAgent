from __future__ import annotations

from datetime import datetime, timezone

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState, StepType
from local_dev_agent.models import ModelRequest, ModelResponse, StopReason, ToolUseBlock
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.storage import JsonFileStateRepository
from local_dev_agent.subagents import SubagentOutcome, SubagentResult, SubagentTask
from local_dev_agent.tools import ToolRegistry
from local_dev_agent.tools.builtin import TaskTool


class ScriptedModel:
    """按顺序返回父 Agent 响应，并保存工具结果回填请求。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一项预设响应。"""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("测试模型没有更多预设响应。")
        return self._responses.pop(0)


class RecordingSubagentRunner:
    """返回确定性结果并记录父循环传入的委派任务。"""

    def __init__(self) -> None:
        self.tasks: list[SubagentTask] = []

    def run(self, task: SubagentTask) -> SubagentResult:
        """模拟已完成的子 Agent。"""

        self.tasks.append(task)
        return SubagentResult.create(
            task_id=task.task_id,
            outcome=SubagentOutcome.SUCCEEDED,
            summary="子 Agent 已完成调查。",
            child_session_id="session-child",
            child_run_id="run-child",
        )


def test_parent_loop_records_task_as_delegate_and_returns_its_structured_result(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="调查项目测试框架。",
            occurred_at=timestamp,
        )
    )
    runner = RecordingSubagentRunner()
    registry = ToolRegistry()
    registry.register(TaskTool(runner))
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-task",
                        name="task",
                        input={
                            "description": "调查测试框架。",
                            "acceptance_criteria": ["返回框架名称"],
                        },
                    ),
                ),
            ),
            ModelResponse.text_completion("父 Agent 已收到子任务结论。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    delegated_step = result.steps[1]
    tool_result = model.requests[1].conversation[2].content[0]
    delegated_task = runner.tasks[0]

    assert delegated_step.step_type is StepType.DELEGATE
    assert delegated_task.parent_session_id == session.session_id
    assert delegated_task.parent_run_id == result.run.run_id
    assert delegated_task.parent_step_id == delegated_step.step_id
    assert tool_result.content == {
        "task_id": delegated_task.task_id,
        "outcome": "succeeded",
        "summary": "子 Agent 已完成调查。",
        "child_session_id": "session-child",
        "child_run_id": "run-child",
        "evidence": [],
        "artifacts": [],
        "unresolved_risks": [],
    }
