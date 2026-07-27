from datetime import datetime, timezone

import pytest

from local_dev_agent.context import (
    ContextBudget,
    ContextManager,
    FileSystemToolResultArtifactStore,
    HistorySummaryCompactor,
    ModelConversationSummarizer,
    ToolResultBudgetCompactor,
)
from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import (
    RunStatus,
    SessionState,
    SessionStatus,
    StepStatus,
)
from local_dev_agent.hooks import (
    HookEvent,
    HookRegistry,
    HookResult,
    HookRunner,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)
from local_dev_agent.models import ModelContextWindowExceededError
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import (
    MessageRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.runtime.errors import AgentLoopExhaustedError
from local_dev_agent.runtime.input_service import UserInputRuntimeService
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry
from local_dev_agent.tools.builtin import (
    CompactContextTool,
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    ReadArtifactTool,
    TodoWriteTool,
    WriteFileTool,
)
from local_dev_agent.todos import (
    JsonFileTodoRepository,
    TODO_REMINDER_MESSAGE,
    TodoReminderPolicy,
    TodoStatus,
)


class ScriptedModel:
    """按预设顺序返回响应，用于验证跨多轮的 Agent Loop。"""

    def __init__(self, responses: tuple[ModelResponse | Exception, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一条预设响应。"""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("测试模型没有更多预设响应。")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RecordingSummarizer:
    """记录 Runtime 请求的应急摘要来源，并返回稳定摘要。"""

    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.snapshots = []

    def summarize(self, snapshot) -> str:
        self.snapshots.append(snapshot)
        return self._summary


class ArtifactReadingModel:
    """模拟从派生上下文取得 Artifact 引用后按需读取的模型。"""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.artifact_refs: list[str] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """按固定三轮路径请求大结果、读取 Artifact 并完成回复。"""

        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-large",
                        name="large_result",
                        input={},
                    ),
                ),
            )
        if len(self.requests) == 2:
            result_block = request.conversation[-1].content[0]
            assert isinstance(result_block, ToolResultBlock)
            artifact_ref = result_block.content["artifact_ref"]
            assert isinstance(artifact_ref, str)
            self.artifact_refs.append(artifact_ref)
            return ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-artifact",
                        name="read_artifact",
                        input={"artifact_ref": artifact_ref, "max_characters": 50},
                    ),
                ),
            )
        if len(self.requests) == 3:
            return ModelResponse.text_completion("已读取 Artifact 的首段内容。")
        raise AssertionError("测试模型收到超出预期的调用次数。")


class BlockingPreToolHook:
    """记录关联信息并阻止工具调用的测试 Hook。"""

    name = "block-tool"

    def __init__(self) -> None:
        self.contexts: list[PreToolUseContext] = []

    def handle(self, context: PreToolUseContext) -> HookResult:
        self.contexts.append(context)
        return HookResult.block("测试权限拒绝。")


class RecordingUserPromptHook:
    """记录已保存输入的测试 Hook。"""

    name = "record-prompt"

    def __init__(self) -> None:
        self.contexts: list[UserPromptSubmitContext] = []

    def handle(self, context: UserPromptSubmitContext) -> HookResult:
        self.contexts.append(context)
        return HookResult.block("停止后续输入审计。")


class RecordingStopHook:
    """记录完成前运行状态的测试 Hook。"""

    name = "record-stop"

    def __init__(self, repository: JsonFileStateRepository) -> None:
        self._repository = repository
        self.contexts: list[StopContext] = []
        self.observed_run_statuses: list[RunStatus] = []

    def handle(self, context: StopContext) -> HookResult:
        self.contexts.append(context)
        run = self._repository.get_run(context.run_id)
        assert run is not None
        self.observed_run_statuses.append(run.status)
        return HookResult.block("停止后续收尾审计。")


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


def test_minimal_agent_loop_passes_system_prompt_without_persisting_it(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 11, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="检查项目状态。",
            occurred_at=timestamp,
        )
    )
    model = FakeModel(ModelResponse.text_completion("项目状态正常。"))

    MinimalAgentLoop(
        repository,
        model,
        conversation_repository=conversation_repository,
        system_prompt="多步骤任务先维护待办清单。",
    ).execute(start, occurred_at=timestamp)

    assert model.requests[0].system_prompt == "多步骤任务先维护待办清单。"
    assert [message.role for message in conversation_repository.get_messages("session-1")] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert all(
        "多步骤任务先维护待办清单。"
        not in block.text
        for message in conversation_repository.get_messages("session-1")
        for block in message.content
        if isinstance(block, TextBlock)
    )


def test_minimal_agent_loop_injects_a_transient_todo_reminder_after_three_tool_turns(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 25, 11, 30, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="检查三个模块并汇总。",
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
            result={"content": "模块正常"},
        )
    )
    model = ScriptedModel(
        (
            *(
                ModelResponse(
                    stop_reason=StopReason.TOOL_USE,
                    content=(
                        ToolUseBlock(
                            tool_use_id=f"toolu-{index}",
                            name="read_file",
                            input={},
                        ),
                    ),
                )
                for index in range(1, 4)
            ),
            ModelResponse.text_completion("三个模块均已检查。"),
        )
    )

    result = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        system_prompt="基础规划提示。",
        todo_reminder_policy=TodoReminderPolicy(max_tool_turns_without_update=3),
    ).execute(start, occurred_at=timestamp)

    assert [request.system_prompt for request in model.requests[:3]] == [
        "基础规划提示。",
        "基础规划提示。",
        "基础规划提示。",
    ]
    assert model.requests[3].system_prompt == (
        f"基础规划提示。\n\n{TODO_REMINDER_MESSAGE}"
    )
    assert result.response.text == "三个模块均已检查。"
    assert all(
        TODO_REMINDER_MESSAGE not in block.text
        for message in conversation_repository.get_messages("session-1")
        for block in message.content
        if isinstance(block, TextBlock)
    )


def test_minimal_agent_loop_triggers_user_prompt_hook_without_changing_the_prompt(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
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
        content="检查项目状态。",
        occurred_at=timestamp,
    )
    start = UserInputRuntimeService(repository).handle(event)
    hook = RecordingUserPromptHook()
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.USER_PROMPT_SUBMIT, hook)
    model = FakeModel(ModelResponse.text_completion("项目状态正常。"))

    result = MinimalAgentLoop(
        repository,
        model,
        hook_runner=HookRunner(hook_registry),
    ).execute(start, occurred_at=timestamp)

    assert hook.contexts[0].session_id == session.session_id
    assert hook.contexts[0].run_id == start.run.run_id
    assert hook.contexts[0].step_id == start.first_step.step_id
    assert hook.contexts[0].prompt == event.content
    assert model.requests[0].conversation[0].content[0].text == event.content
    assert result.response.text == "项目状态正常。"


def test_minimal_agent_loop_triggers_stop_hook_before_persisting_completion(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)
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
        content="检查项目状态。",
        occurred_at=timestamp,
    )
    start = UserInputRuntimeService(repository).handle(event)
    hook = RecordingStopHook(repository)
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.STOP, hook)
    response = ModelResponse.text_completion("项目状态正常。")
    model = FakeModel(response)

    result = MinimalAgentLoop(
        repository,
        model,
        hook_runner=HookRunner(hook_registry),
    ).execute(start, occurred_at=timestamp)

    assert hook.contexts[0].session_id == session.session_id
    assert hook.contexts[0].run_id == start.run.run_id
    assert hook.contexts[0].step_id == start.first_step.step_id
    assert hook.contexts[0].response is response
    assert hook.observed_run_statuses == [RunStatus.RUNNING]
    assert result.run.status is RunStatus.COMPLETED


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
    execution_context = tool.contexts[0]
    assert execution_context is not None
    assert execution_context.session_id == session.session_id
    assert execution_context.run_id == result.run.run_id
    assert execution_context.step_id == result.steps[1].step_id
    assert execution_context.call_id == "toolu-1"
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


def test_minimal_agent_loop_returns_the_real_write_file_result(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 10, 30, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
            content="创建待办文件。",
            occurred_at=timestamp,
        )
    )
    registry = ToolRegistry()
    registry.register(WriteFileTool(workspace))
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="write_file",
                        input={"path": "notes/todo.txt", "content": "完成测试"},
                    ),
                ),
            ),
            ModelResponse.text_completion("已创建待办文件。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.content == {"path": "notes/todo.txt", "bytes_written": 12}
    assert (workspace / "notes" / "todo.txt").read_text(encoding="utf-8") == "完成测试"
    assert result.response.text == "已创建待办文件。"


def test_minimal_agent_loop_returns_the_real_edit_file_result(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 10, 45, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target_file = workspace / "status.txt"
    target_file.write_text("待办\n待办", encoding="utf-8")
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
            content="修改状态文件。",
            occurred_at=timestamp,
        )
    )
    registry = ToolRegistry()
    registry.register(EditFileTool(workspace))
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="edit_file",
                        input={
                            "path": "status.txt",
                            "old_text": "待办",
                            "new_text": "进行中",
                        },
                    ),
                ),
            ),
            ModelResponse.text_completion("已修改状态文件。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.content == {"path": "status.txt", "replacements": 1}
    assert target_file.read_text(encoding="utf-8") == "进行中\n待办"
    assert result.response.text == "已修改状态文件。"


def test_minimal_agent_loop_returns_the_real_todo_write_result(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
            content="列出并更新实现步骤。",
            occurred_at=timestamp,
        )
    )
    registry = ToolRegistry()
    todo_repository = JsonFileTodoRepository(workspace / "var" / "state" / "todos")
    registry.register(TodoWriteTool(todo_repository))
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-1",
                        name="todo_write",
                        input={
                            "todos": [
                                {
                                    "content": "实现 JSON 仓储",
                                    "status": "completed",
                                },
                                {
                                    "content": "注册 todo_write 工具",
                                    "status": "in_progress",
                                    "active_form": "正在注册 todo_write 工具",
                                },
                            ],
                        },
                    ),
                ),
            ),
            ModelResponse.text_completion("待办清单已更新。"),
        )
    )

    result = MinimalAgentLoop(repository, model, registry).execute(
        start,
        occurred_at=timestamp,
    )

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.content == {
        "todo_list_id": "default",
        "total": 2,
        "pending": 0,
        "in_progress": 1,
        "completed": 1,
    }
    assert todo_repository.load("default").todos[0].status is TodoStatus.COMPLETED
    assert result.response.text == "待办清单已更新。"


def test_minimal_agent_loop_reuses_persisted_session_history_across_runs(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    registry = ToolRegistry()
    registry.register(
        FakeTool(
            definition=ToolDefinition(
                name="list_files",
                description="列出文件。",
                parameters={"type": "object", "properties": {}},
            ),
            result={"files": ["README.md"], "truncated": False},
        )
    )
    registry.register(
        FakeTool(
            definition=ToolDefinition(
                name="read_file",
                description="读取文件。",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
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
                        tool_use_id="toolu-list",
                        name="list_files",
                        input={},
                    ),
                ),
            ),
            ModelResponse.text_completion("目录中有 README.md。"),
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-read",
                        name="read_file",
                        input={"path": "README.md"},
                    ),
                ),
            ),
            ModelResponse.text_completion("README 的内容是项目说明。"),
        )
    )
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
    )

    first_start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="我目录有哪些文件？",
            occurred_at=timestamp,
        )
    )
    first_result = loop.execute(first_start, occurred_at=timestamp)
    second_start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(
            session_id=first_result.session.session_id,
            content="告诉我里面前 20 行是什么。",
            occurred_at=timestamp,
        )
    )

    result = loop.execute(second_start, occurred_at=timestamp)

    second_run_request = model.requests[2]
    assert [message.role for message in second_run_request.conversation] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert second_run_request.conversation[2].content[0].content == {
        "files": ["README.md"],
        "truncated": False,
    }
    assert isinstance(second_run_request.conversation[3].content[0], TextBlock)
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


def test_minimal_agent_loop_returns_pre_tool_hook_block_to_the_model(tmp_path) -> None:
    timestamp = datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc)
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
    tool_registry = ToolRegistry()
    tool_registry.register(tool)
    hook = BlockingPreToolHook()
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.PRE_TOOL_USE, hook)
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
            ModelResponse.text_completion("工具调用已被拒绝。"),
        )
    )

    result = MinimalAgentLoop(
        repository,
        model,
        tool_registry,
        hook_runner=HookRunner(hook_registry),
    ).execute(start, occurred_at=timestamp)

    tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.is_error is True
    assert tool_result.content["error"]["type"] == "ToolHookBlockedError"  # type: ignore[index]
    assert tool.calls == []
    assert hook.contexts[0].session_id == session.session_id
    assert hook.contexts[0].run_id == start.run.run_id
    assert hook.contexts[0].step_id != start.first_step.step_id
    assert hook.contexts[0].request.call_id == "toolu-1"
    assert result.response.text == "工具调用已被拒绝。"


def test_minimal_agent_loop_uses_a_summary_view_without_rewriting_transcript(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="甲" * 500,
            occurred_at=timestamp,
        )
    )
    model = ScriptedModel(
        (
            ModelResponse.text_completion("当前目标：继续处理用户请求。"),
            ModelResponse.text_completion("已完成处理。"),
        )
    )
    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=200,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(ModelConversationSummarizer(model)),
    )

    result = MinimalAgentLoop(
        repository,
        model,
        conversation_repository=conversation_repository,
        context_manager=context_manager,
    ).execute(start, occurred_at=timestamp)

    summary_request, final_request = model.requests
    assert summary_request.tools == ()
    assert final_request.conversation[0].content == (
        TextBlock("[已压缩的历史摘要]\n\n当前目标：继续处理用户请求。"),
    )
    assert conversation_repository.get_messages(session.session_id)[0].content == (
        TextBlock("甲" * 500),
    )
    assert result.response.text == "已完成处理。"


def test_minimal_agent_loop_uses_an_artifact_view_without_rewriting_tool_transcript(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 27, 9, 30, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="读取大型日志。",
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
            result={"content": "甲" * 1_000},
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
            ModelResponse.text_completion("已读取大型日志。"),
        )
    )

    class UnexpectedSummarizer:
        def summarize(self, snapshot) -> str:
            raise AssertionError("当前预算充足，不应生成历史摘要。")

    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts"),
            max_total_bytes=100,
            minimum_artifact_bytes=20,
        ),
        HistorySummaryCompactor(UnexpectedSummarizer()),
    )

    result = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        context_manager=context_manager,
    ).execute(start, occurred_at=timestamp)

    compacted_tool_result = model.requests[1].conversation[2].content[0]
    assert isinstance(compacted_tool_result, ToolResultBlock)
    assert "artifact_ref" in compacted_tool_result.content
    persisted_tool_result = conversation_repository.get_messages(session.session_id)[2].content[0]
    assert isinstance(persisted_tool_result, ToolResultBlock)
    assert persisted_tool_result.content == {"content": "甲" * 1_000}
    assert result.response.text == "已读取大型日志。"


def test_minimal_agent_loop_retries_once_with_an_emergency_summary_view(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="甲" * 500,
            occurred_at=timestamp,
        )
    )
    model = ScriptedModel(
        (
            ModelContextWindowExceededError("Provider 拒绝原始上下文。"),
            ModelResponse.text_completion("已在压缩上下文后完成。"),
        )
    )
    summarizer = RecordingSummarizer("当前目标：继续处理用户请求。")
    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(summarizer),
    )

    result = MinimalAgentLoop(
        repository,
        model,
        conversation_repository=conversation_repository,
        context_manager=context_manager,
    ).execute(start, occurred_at=timestamp)

    assert len(model.requests) == 2
    assert model.requests[0].conversation[0].content == (TextBlock("甲" * 500),)
    assert model.requests[1].conversation[0].content == (
        TextBlock("[已压缩的历史摘要]\n\n当前目标：继续处理用户请求。"),
    )
    assert len(summarizer.snapshots) == 1
    assert conversation_repository.get_messages(session.session_id) == (
        ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock("甲" * 500),),
        ),
        ModelMessage(
            role=MessageRole.ASSISTANT,
            content=(TextBlock("已在压缩上下文后完成。"),),
        ),
    )
    assert result.response.text == "已在压缩上下文后完成。"


def test_minimal_agent_loop_stops_after_the_single_emergency_retry(tmp_path) -> None:
    timestamp = datetime(2026, 7, 27, 10, 15, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="甲" * 500,
            occurred_at=timestamp,
        )
    )
    model = ScriptedModel(
        (
            ModelContextWindowExceededError("首次超限。"),
            ModelContextWindowExceededError("应急重试仍超限。"),
        )
    )
    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(RecordingSummarizer("当前目标：继续处理用户请求。")),
    )

    with pytest.raises(ModelContextWindowExceededError, match="应急重试仍超限"):
        MinimalAgentLoop(
            repository,
            model,
            conversation_repository=conversation_repository,
            context_manager=context_manager,
        ).execute(start, occurred_at=timestamp)

    assert len(model.requests) == 2
    assert [message.role for message in conversation_repository.get_messages(session.session_id)] == [
        MessageRole.USER
    ]


def test_minimal_agent_loop_does_not_retry_non_context_provider_errors(tmp_path) -> None:
    timestamp = datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="检查项目状态。",
            occurred_at=timestamp,
        )
    )
    model = ScriptedModel((RuntimeError("网络不可用"),))
    summarizer = RecordingSummarizer("不应生成摘要。")
    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(summarizer),
    )

    with pytest.raises(RuntimeError, match="网络不可用"):
        MinimalAgentLoop(
            repository,
            model,
            conversation_repository=conversation_repository,
            context_manager=context_manager,
        ).execute(start, occurred_at=timestamp)

    assert len(model.requests) == 1
    assert summarizer.snapshots == []
    assert [message.role for message in conversation_repository.get_messages(session.session_id)] == [
        MessageRole.USER
    ]


def test_minimal_agent_loop_compacts_the_next_request_after_a_successful_compact_tool_call(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 27, 10, 45, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="先整理上下文再继续。",
            occurred_at=timestamp,
        )
    )
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-compact",
                        name="compact",
                        input={},
                    ),
                ),
            ),
            ModelResponse.text_completion("已在压缩上下文后继续处理。"),
        )
    )
    summarizer = RecordingSummarizer("当前目标：继续处理用户请求。")
    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(tmp_path / "artifacts")
        ),
        HistorySummaryCompactor(summarizer),
    )
    registry = ToolRegistry()
    registry.register(CompactContextTool())

    result = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        context_manager=context_manager,
    ).execute(start, occurred_at=timestamp)

    assert [definition.name for definition in model.requests[0].tools] == ["compact"]
    assert model.requests[1].conversation[0].content == (
        TextBlock("[已压缩的历史摘要]\n\n当前目标：继续处理用户请求。"),
    )
    assert len(summarizer.snapshots) == 1
    persisted_messages = conversation_repository.get_messages(session.session_id)
    assert [message.role for message in persisted_messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert persisted_messages[2].content == (
        ToolResultBlock(
            tool_use_id="toolu-compact",
            content={"requested": True},
        ),
    )
    assert result.response.text == "已在压缩上下文后继续处理。"


def test_minimal_agent_loop_allows_the_model_to_read_an_artifact_reference(tmp_path) -> None:
    timestamp = datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
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
            content="读取大型日志并检查开头。",
            occurred_at=timestamp,
        )
    )
    store = FileSystemToolResultArtifactStore(tmp_path / "artifacts")
    registry = ToolRegistry()
    registry.register(
        FakeTool(
            definition=ToolDefinition(
                name="large_result",
                description="返回大型结果。",
                parameters={"type": "object", "properties": {}},
            ),
            result={"content": "甲" * 1_000},
        )
    )
    registry.register(ReadArtifactTool(store))
    model = ArtifactReadingModel()
    context_manager = ContextManager(
        ContextBudget(
            context_window_tokens=10_000,
            max_output_tokens=1,
            safety_margin_tokens=1,
        ),
        ToolResultBudgetCompactor(
            store,
            max_total_bytes=100,
            minimum_artifact_bytes=20,
        ),
        HistorySummaryCompactor(RecordingSummarizer("不应生成历史摘要。")),
    )

    result = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        context_manager=context_manager,
    ).execute(start, occurred_at=timestamp)

    assert len(model.artifact_refs) == 1
    assert model.artifact_refs[0].startswith("tool-results/")
    assert model.artifact_refs[0].endswith(".json")
    assert (tmp_path / "artifacts" / model.artifact_refs[0]).is_file()
    persisted_large_result = conversation_repository.get_messages(session.session_id)[2]
    assert persisted_large_result.content == (
        ToolResultBlock(
            tool_use_id="toolu-large",
            content={"content": "甲" * 1_000},
        ),
    )
    assert result.response.text == "已读取 Artifact 的首段内容。"
