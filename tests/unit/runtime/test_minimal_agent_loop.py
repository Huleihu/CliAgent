from datetime import datetime, timezone

import pytest

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import (
    RunStatus,
    SessionState,
    SessionStatus,
    StepStatus,
)
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import (
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.runtime.errors import AgentLoopExhaustedError
from local_dev_agent.runtime.input_service import UserInputRuntimeService
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry
from local_dev_agent.tools.builtin import ListFilesTool, ReadFileTool


class ScriptedModel:
    """按预设顺序返回响应，用于验证跨多轮的 Agent Loop。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一条预设响应。"""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("测试模型没有更多预设响应。")
        return self._responses.pop(0)


def test_minimal_agent_loop_completes_a_text_response_and_persists_states(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    event = UserInputEvent.create(
        event_id="event-1",
        session_id=session.session_id,
        content="检查项目状态。",
        occurred_at=timestamp,
    )
    start = UserInputRuntimeService(repository).handle(event)
    model = FakeModel(ModelResponse.text_completion("项目状态正常。"))

    result = MinimalAgentLoop(repository, model).execute(
        start,
        occurred_at=timestamp,
    )

    assert result.response.text == "项目状态正常。"
    assert model.requests[0].conversation[0].content[0].text == event.content
    assert result.step.status is StepStatus.SUCCEEDED
    assert result.run.status is RunStatus.COMPLETED
    assert result.session.status is SessionStatus.ACTIVE
    assert result.session.active_run_id is None
    assert repository.get_session(session.session_id) == result.session
    assert repository.get_run(result.run.run_id) == result.run
    assert repository.get_step(result.step.step_id) == result.step
    assert [item.target_status for item in result.run.transition_history] == [
        RunStatus.RECOVERING,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]


def test_minimal_agent_loop_executes_tool_and_returns_its_result_to_the_model(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    event = UserInputEvent.create(
        session_id=session.session_id,
        content="读取 README。",
        occurred_at=timestamp,
    )
    start = UserInputRuntimeService(repository).handle(event)
    tool = FakeTool(
        definition=ToolDefinition(
            name="read_file",
            description="读取文本文件。",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        result={"content": "项目说明"},
    )
    registry = ToolRegistry()
    registry.register(tool)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="read_file",
                        input={"path": "README.md"},
                    ),
                ),
            ),
            ModelResponse.text_completion("README 已读取。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    assert result.response.text == "README 已读取。"
    assert result.run.status is RunStatus.COMPLETED
    assert tool.calls == [{"path": "README.md"}]
    assert model.requests[0].tools == (tool.definition,)
    assert model.requests[1].conversation[2].content[0].content == {
        "content": "项目说明"
    }
    assert [step.step_type for step in result.steps] == [
        "plan",
        "tool",
        "model",
    ]
    assert [step.status for step in result.steps] == [
        StepStatus.SUCCEEDED,
        StepStatus.SUCCEEDED,
        StepStatus.SUCCEEDED,
    ]


def test_minimal_agent_loop_returns_listed_files_from_the_real_read_only_tool(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("项目说明", encoding="utf-8")
    repository = JsonFileStateRepository(tmp_path / "state")
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id=str(workspace),
        created_at=timestamp,
    )
    repository.save_session(session)
    start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="列出 Markdown 文件。",
            occurred_at=timestamp,
        )
    )
    registry = ToolRegistry()
    registry.register(ListFilesTool(workspace))
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="list_files",
                        input={"pattern": "*.md"},
                    ),
                ),
            ),
            ModelResponse.text_completion("找到 README.md。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.content == {"files": ["README.md"], "truncated": False}
    assert result.response.text == "找到 README.md。"


def test_minimal_agent_loop_returns_text_from_the_real_read_only_tool(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("项目说明", encoding="utf-8")
    repository = JsonFileStateRepository(tmp_path / "state")
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id=str(workspace),
        created_at=timestamp,
    )
    repository.save_session(session)
    start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="读取 README。",
            occurred_at=timestamp,
        )
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool(workspace))
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="read_file",
                        input={"path": "README.md"},
                    ),
                ),
            ),
            ModelResponse.text_completion("README 的内容是项目说明。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.content == {
        "path": "README.md",
        "content": "项目说明",
        "total_lines": 1,
        "truncated": False,
    }
    assert result.response.text == "README 的内容是项目说明。"


def test_minimal_agent_loop_exhausts_after_the_configured_model_turn_limit(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="读取 README。",
            occurred_at=timestamp,
        )
    )
    registry = ToolRegistry()
    registry.register(
        FakeTool(
            definition=ToolDefinition(
                name="read_file",
                description="读取文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
            result={"content": "项目说明"},
        )
    )
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="read_file",
                        input={},
                    ),
                ),
            ),
        )
    )

    with pytest.raises(AgentLoopExhaustedError, match="最大模型调用轮次"):
        MinimalAgentLoop(repository, model, registry, max_turns=1).execute(
            start,
            occurred_at=timestamp,
        )

    persisted_run = repository.get_run(start.run.run_id)
    persisted_session = repository.get_session(session.session_id)
    assert persisted_run is not None
    assert persisted_session is not None
    assert persisted_run.status is RunStatus.EXHAUSTED
    assert persisted_session.active_run_id is None


def test_minimal_agent_loop_returns_tool_failure_to_the_next_model_turn(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="读取不存在的工具。",
            occurred_at=timestamp,
        )
    )
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="missing_tool",
                        input={},
                    ),
                ),
            ),
            ModelResponse.text_completion("该工具不可用。"),
        )
    )

    result = MinimalAgentLoop(repository, model).execute(
        start,
        occurred_at=timestamp,
    )

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.is_error is True
    assert tool_result.content["error"]["type"] == "ToolNotFoundError"  # type: ignore[index]
    assert [step.status for step in result.steps] == [
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.SUCCEEDED,
    ]
