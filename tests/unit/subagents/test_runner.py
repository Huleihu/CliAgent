from __future__ import annotations

from pathlib import Path

import pytest

from local_dev_agent.domain.state import RunStatus, SessionState
from local_dev_agent.hooks import (
    HookEvent,
    HookRegistry,
    HookResult,
    HookRunner,
    PreToolUseContext,
)
from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from local_dev_agent.storage import JsonFileConversationRepository, JsonFileStateRepository
from local_dev_agent.subagents import (
    SubagentOutcome,
    SubagentParentSessionNotFoundError,
    SubagentPolicy,
    SubagentTask,
    SubagentToolRegistryFactory,
    SynchronousSubagentRunner,
)
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry


class ScriptedModel:
    """按顺序返回响应并保留请求，用于验证子上下文隔离。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一项预设响应。"""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("测试模型没有更多预设响应。")
        return self._responses.pop(0)


class RecordingPreToolHook:
    """记录子 Agent 工具调用关联。"""

    name = "record-subagent-tool"

    def __init__(self) -> None:
        self.contexts: list[PreToolUseContext] = []

    def handle(self, context: PreToolUseContext) -> HookResult:
        """保留上下文并继续执行。"""

        self.contexts.append(context)
        return HookResult.continue_()


def _tool(name: str) -> FakeTool:
    return FakeTool(
        definition=ToolDefinition(
            name=name,
            description=f"测试工具：{name}。",
            parameters={"type": "object", "properties": {}},
        ),
        result={"tool": name},
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("list_files", "read_file", "write_file", "edit_file"):
        registry.register(_tool(name))
    return registry


def _save_parent_session(repository: JsonFileStateRepository) -> SessionState:
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
    )
    repository.save_session(session)
    return session


def _task() -> SubagentTask:
    return SubagentTask.create(
        task_id="task-1",
        parent_session_id="session-parent",
        parent_run_id="run-parent",
        parent_step_id="step-parent",
        description="调查测试框架。",
        acceptance_criteria=("返回框架名称",),
    )


def _runner(
    state_repository: JsonFileStateRepository,
    conversation_repository: JsonFileConversationRepository,
    model: ScriptedModel,
    *,
    policy: SubagentPolicy | None = None,
    hook_runner: HookRunner | None = None,
) -> SynchronousSubagentRunner:
    factory = SubagentToolRegistryFactory(_registry(), policy or SubagentPolicy())
    return SynchronousSubagentRunner(
        state_repository,
        conversation_repository,
        model,
        factory,
        hook_runner=hook_runner,
    )


def test_runner_creates_an_isolated_session_run_and_transcript(tmp_path: Path) -> None:
    state_repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    parent_session = _save_parent_session(state_repository)
    parent_message = ModelMessage(
        role=MessageRole.USER,
        content=(TextBlock(text="父对话中的私有信息。"),),
    )
    conversation_repository.append_messages(parent_session.session_id, (parent_message,))
    model = ScriptedModel((ModelResponse.text_completion("项目使用 pytest。"),))

    result = _runner(state_repository, conversation_repository, model).run(_task())

    child_session = state_repository.get_session(result.child_session_id)
    child_run = state_repository.get_run(result.child_run_id)
    parent_messages = conversation_repository.get_messages(parent_session.session_id)
    child_messages = conversation_repository.get_messages(result.child_session_id)
    request = model.requests[0]

    assert result.outcome is SubagentOutcome.SUCCEEDED
    assert result.summary == "项目使用 pytest。"
    assert child_session is not None
    assert child_session.session_id != parent_session.session_id
    assert (child_session.tenant_id, child_session.user_id, child_session.project_id) == (
        parent_session.tenant_id,
        parent_session.user_id,
        parent_session.project_id,
    )
    assert child_run is not None and child_run.status is RunStatus.COMPLETED
    assert parent_messages == (parent_message,)
    assert child_messages[0].content[0].text == "调查测试框架。\n\n验收标准：\n- 返回框架名称"
    assert child_messages[-1].content[0].text == "项目使用 pytest。"
    assert request.system_prompt == SubagentPolicy().system_prompt
    assert [definition.name for definition in request.tools] == [
        "edit_file",
        "list_files",
        "read_file",
        "write_file",
    ]
    assert "父对话中的私有信息" not in request.conversation[0].content[0].text


def test_runner_reuses_permission_hooks_for_child_tool_calls(tmp_path: Path) -> None:
    state_repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    _save_parent_session(state_repository)
    hook = RecordingPreToolHook()
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.PRE_TOOL_USE, hook)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-child",
                        name="read_file",
                        input={},
                    ),
                ),
            ),
            ModelResponse.text_completion("调查完成。"),
        )
    )

    result = _runner(
        state_repository,
        conversation_repository,
        model,
        hook_runner=HookRunner(hook_registry),
    ).run(_task())

    assert result.outcome is SubagentOutcome.SUCCEEDED
    assert len(hook.contexts) == 1
    assert hook.contexts[0].session_id == result.child_session_id
    assert hook.contexts[0].run_id == result.child_run_id
    assert hook.contexts[0].request.call_id == "toolu-child"


def test_runner_returns_an_exhausted_result_for_a_bounded_child_loop(tmp_path: Path) -> None:
    state_repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    _save_parent_session(state_repository)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-child",
                        name="read_file",
                        input={},
                    ),
                ),
            ),
        )
    )

    result = _runner(
        state_repository,
        conversation_repository,
        model,
        policy=SubagentPolicy.create(max_turns=1),
    ).run(_task())

    child_run = state_repository.get_run(result.child_run_id)
    child_session = state_repository.get_session(result.child_session_id)

    assert result.outcome is SubagentOutcome.EXHAUSTED
    assert "最大模型调用轮次“1”" in result.summary
    assert child_run is not None and child_run.status is RunStatus.EXHAUSTED
    assert child_session is not None and child_session.active_run_id is None


def test_runner_rejects_a_missing_parent_session(tmp_path: Path) -> None:
    state_repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    model = ScriptedModel((ModelResponse.text_completion("不会调用。"),))

    with pytest.raises(SubagentParentSessionNotFoundError, match="session-parent"):
        _runner(state_repository, conversation_repository, model).run(_task())

    assert model.requests == []


def test_runner_rejects_invalid_task_and_factory_dependencies(tmp_path: Path) -> None:
    state_repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    model = ScriptedModel((ModelResponse.text_completion("不会调用。"),))

    with pytest.raises(TypeError, match="工具目录工厂"):
        SynchronousSubagentRunner(
            state_repository,
            conversation_repository,
            model,
            object(),  # type: ignore[arg-type]
        )

    runner = _runner(state_repository, conversation_repository, model)
    with pytest.raises(TypeError, match="只能执行 SubagentTask"):
        runner.run(object())  # type: ignore[arg-type]
