from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from local_dev_agent.background_tasks import (
    BackgroundTask,
    CommandExecutionResult,
    InMemoryBackgroundTaskRepository,
)
from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookDecision, HookEvent, PreToolUseContext
from local_dev_agent.main import create_permission_hook_runner
from local_dev_agent.main import create_context_manager
from local_dev_agent.main import create_memory_loader
from local_dev_agent.main import create_task_service
from local_dev_agent.cron import LockCronExecutionGate
from local_dev_agent.main import create_subagent_runner
from local_dev_agent.main import create_transient_recovery_executor
from local_dev_agent.main import create_tool_registry
from local_dev_agent.main import default_workspace
from local_dev_agent.main import create_output_budget_upgrade_policy
from local_dev_agent.main import create_output_continuation_policy
from local_dev_agent.main import execute_prompt
from local_dev_agent.main import register_cli_background_task_capability
from local_dev_agent.main import register_cli_cron_capability
from local_dev_agent.main import register_cli_team_capability
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models import DeepSeekSettings
from local_dev_agent.context import ContextInputSnapshot, ContextManager
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
from local_dev_agent.skills import SkillCatalog, SkillDocument, SkillMetadata
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.system_prompt import (
    BACKGROUND_TASK_SYSTEM_PROMPT,
    TASK_DELEGATION_SYSTEM_PROMPT,
    TASK_SYSTEM_PROMPT,
    TODO_PLANNING_SYSTEM_PROMPT,
    create_cli_system_prompt_provider,
)
from local_dev_agent.todos import TodoReminderPolicy
from local_dev_agent.subagents import SubagentPolicy, SubagentToolRegistryFactory
from local_dev_agent.tools import ToolCallRequest, ToolExecutionContext
from local_dev_agent.tools.builtin import TaskTool


def test_execute_prompt_connects_input_service_to_agent_loop(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="local",
        user_id="local",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    loop = MinimalAgentLoop(
        repository,
        FakeModel(ModelResponse.text_completion("项目状态正常。")),
    )

    result = execute_prompt(
        prompt="检查项目状态。",
        session=session,
        repository=repository,
        loop=loop,
    )

    assert result.response.text == "项目状态正常。"
    assert result.session.active_run_id is None


def test_create_tool_registry_registers_the_read_only_file_listing_tool(tmp_path) -> None:
    registry = create_tool_registry(tmp_path)

    assert [definition.name for definition in registry.list_definitions()] == [
        "compact",
        "edit_file",
        "list_files",
        "read_artifact",
        "read_file",
        "task_claim",
        "task_complete",
        "task_create",
        "task_get",
        "task_list",
        "todo_write",
        "write_file",
    ]


def test_create_task_service_uses_the_workspace_task_state_root(tmp_path) -> None:
    service = create_task_service(tmp_path)

    task = service.create_task(subject="建立表结构。")

    assert (tmp_path / "var" / "state" / "tasks" / f"{task.task_id}.json").is_file()


def test_create_context_manager_assembles_the_s8_pipeline(tmp_path) -> None:
    manager = create_context_manager(
        workspace=tmp_path,
        model=FakeModel(ModelResponse.text_completion("不会调用。")),
        max_output_tokens=8_000,
    )

    assert isinstance(manager, ContextManager)


def test_create_transient_recovery_executor_uses_deepseek_model_configuration() -> None:
    executor = create_transient_recovery_executor(
        DeepSeekSettings(
            api_key="测试密钥",
            base_url="https://example.test/anthropic",
            model="primary-model",
            fallback_model="fallback-model",
            max_tokens=8_000,
        )
    )

    assert executor.initial_state().current_model_id == "primary-model"


def test_create_output_budget_upgrade_policy_uses_the_configured_initial_budget() -> None:
    policy = create_output_budget_upgrade_policy(
        DeepSeekSettings(
            api_key="测试密钥",
            base_url="https://example.test/anthropic",
            model="primary-model",
            max_tokens=8_000,
        )
    )

    assert policy.initial_max_output_tokens == 8_000
    assert policy.escalated_max_output_tokens == 64_000
    assert policy.can_upgrade


def test_create_output_continuation_policy_uses_the_s11_default_limit() -> None:
    policy = create_output_continuation_policy()

    assert policy.max_continuations == 3


def test_create_memory_loader_uses_the_workspace_memory_root(tmp_path) -> None:
    loader = create_memory_loader(
        workspace=tmp_path,
        model=FakeModel(ModelResponse.text_completion("不会调用。")),
    )

    assert loader.load(session_id="session-1", run_id="run-1", query="检查状态。").catalog.entries == ()


def test_create_context_manager_persists_rebuilt_checkpoints_under_the_cli_state_root(
    tmp_path,
) -> None:
    manager = create_context_manager(
        workspace=tmp_path,
        model=FakeModel(ModelResponse.text_completion("当前目标：继续开发。")),
        max_output_tokens=8_000,
    )
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(role=MessageRole.USER, content=(TextBlock("检查当前状态。"),)),
        ),
    )

    package = manager.prepare(snapshot, force_history_compaction=True)

    assert package.history_compacted
    assert (
        tmp_path / "var" / "state" / "history-summary-checkpoints" / "session-1.json"
    ).is_file()


def _skill_catalog() -> SkillCatalog:
    return SkillCatalog(
        documents=(
            SkillDocument(
                metadata=SkillMetadata(
                    name="code-review",
                    description="审查代码中的缺陷。",
                ),
                source_directory="skills/code-review",
                content="---\nname: code-review\n---\n# 完整技能正文\n",
            ),
        )
    )


def test_cli_skill_composition_registers_parent_tool_and_keeps_body_out_of_prompt(
    tmp_path,
) -> None:
    catalog = _skill_catalog()
    registry = create_tool_registry(tmp_path, skill_catalog=catalog)
    prompt = create_cli_system_prompt_provider(
        workspace=tmp_path,
        registry=registry,
        skill_catalog=catalog,
    ).get_system_prompt()

    assert "load_skill" in [definition.name for definition in registry.list_definitions()]
    assert "code-review" in prompt  # type: ignore[operator]
    assert "审查代码中的缺陷。" in prompt  # type: ignore[operator]
    assert "完整技能正文" not in prompt  # type: ignore[operator]


def test_create_permission_hook_runner_registers_the_s3_policy(tmp_path) -> None:
    request = ToolCallRequest(
        name="bash",
        arguments={"command": "sudo reboot"},
    )

    result = create_permission_hook_runner(tmp_path).trigger(
        HookEvent.PRE_TOOL_USE,
        PreToolUseContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            request=request,
        ),
    )

    assert result.decision is HookDecision.BLOCK
    assert "sudo" in result.message  # type: ignore[operator]


def test_default_workspace_is_the_project_sandbox_directory() -> None:
    expected_workspace = Path(__file__).resolve().parents[2] / "sandbox"

    assert default_workspace() == expected_workspace.resolve()


def test_cli_todo_planning_prompt_describes_the_workflow_without_a_tool_name() -> None:
    assert "待办清单" in TODO_PLANNING_SYSTEM_PROMPT
    assert "更新待办状态" in TODO_PLANNING_SYSTEM_PROMPT
    assert "todo_write" not in TODO_PLANNING_SYSTEM_PROMPT


def test_cli_system_prompt_adds_bounded_task_delegation_guidance() -> None:
    assert "受控委派能力" in TASK_DELEGATION_SYSTEM_PROMPT
    assert "简单任务不要委派" in TASK_DELEGATION_SYSTEM_PROMPT
    assert "task" not in TASK_DELEGATION_SYSTEM_PROMPT


def test_cli_task_system_prompt_distinguishes_project_tasks_from_todo_steps() -> None:
    assert "跨会话" in TASK_SYSTEM_PROMPT
    assert "待办清单" in TASK_SYSTEM_PROMPT
    assert "task_create" not in TASK_SYSTEM_PROMPT


class ScriptedModel:
    """按顺序返回父子 Agent 响应，验证 CLI 装配闭环。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一项预设响应。"""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("测试模型没有更多预设响应。")
        return self._responses.pop(0)


class SignalingBackgroundTaskRepository:
    """在终态写回后发出事件，让 CLI 闭环测试不依赖线程竞速。"""

    def __init__(self) -> None:
        self._repository = InMemoryBackgroundTaskRepository()
        self.terminal_saved = Event()

    def add(self, task: BackgroundTask) -> BackgroundTask:
        return self._repository.add(task)

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._repository.get(task_id)

    def list_for_session(self, session_id: str) -> tuple[BackgroundTask, ...]:
        return self._repository.list_for_session(session_id)

    def replace(self, task: BackgroundTask) -> BackgroundTask:
        saved_task = self._repository.replace(task)
        if saved_task.is_terminal:
            self.terminal_saved.set()
        return saved_task


class CoordinatedCommandRunner:
    """使用 Event 控制后台完成时点，避免测试使用真实等待。"""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        self.started.set()
        if not self.release.wait(timeout=1):
            raise AssertionError("测试未允许后台命令结束。")
        return CommandExecutionResult(exit_code=0, output="后台检查完成。")


class BackgroundTaskCliModel:
    """在两次父工具调用之间释放后台任务，验证通知回填闭环。"""

    def __init__(
        self,
        command_runner: CoordinatedCommandRunner,
        repository: SignalingBackgroundTaskRepository,
    ) -> None:
        self._command_runner = command_runner
        self._repository = repository
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        request_number = len(self.requests)
        if request_number == 1:
            return ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-background",
                        name="bash",
                        input={
                            "command": "python -m pytest",
                            "run_in_background": True,
                        },
                    ),
                ),
            )
        if request_number == 2:
            if not self._command_runner.started.wait(timeout=1):
                raise AssertionError("后台命令线程没有启动。")
            self._command_runner.release.set()
            if not self._repository.terminal_saved.wait(timeout=1):
                raise AssertionError("后台任务终态没有写回。")
            return ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-list-files",
                        name="list_files",
                        input={},
                    ),
                ),
            )
        if request_number == 3:
            return ModelResponse.text_completion("后台检查完成，已继续检查工作区。")
        raise AssertionError("测试模型收到超出预期的请求。")


class FixedCronClock:
    """为 CLI Cron 装配测试提供固定的到期分钟。"""

    def now(self) -> datetime:
        return datetime(2026, 7, 30, 9, tzinfo=timezone.utc)


class StopAfterFirstCronWait:
    """首次轮询后停止对应 Runner，避免测试依赖真实等待。"""

    def wait(self, stop_event: Event, timeout_seconds: float) -> bool:
        stop_event.set()
        return True


class InlineCronThreadFactory:
    """同步运行两个 cron 线程目标，稳定验证 CLI 组合。"""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start(self, *, target, name: str) -> object:
        self.names.append(name)
        target()
        return object()


class StopAfterFirstTeamWait:
    """让成员 Runner 在首次检查后停止，避免 CLI 组合测试出现真实等待。"""

    def wait(self, *, stop_event: Event, wake_event: Event, timeout_seconds: float) -> bool:
        stop_event.set()
        return True


class InlineTeamThreadFactory:
    """同步执行 Team Runner 目标，便于验证成员注册会启动 Runner。"""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start(self, *, target, name: str) -> object:
        self.names.append(name)
        target()
        return object()


def test_cli_team_composition_registers_parent_tools_and_starts_registered_member(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = workspace / "var" / "state"
    repository = JsonFileStateRepository(state_root)
    parent_session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    child_session = SessionState.create(
        session_id="session-child",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(parent_session)
    repository.save_session(child_session)
    registry = create_tool_registry(workspace)
    model = FakeModel(ModelResponse.text_completion("成员处理完成。"))
    loop = MinimalAgentLoop(
        repository,
        model,
    )
    thread_factory = InlineTeamThreadFactory()
    capability = register_cli_team_capability(
        workspace=workspace,
        registry=registry,
        repository=repository,
        loop=loop,
        execution_gate=LockCronExecutionGate(),
        waiter=StopAfterFirstTeamWait(),
        thread_factory=thread_factory,  # type: ignore[arg-type]
    )
    context = ToolExecutionContext(
        session_id=parent_session.session_id,
        run_id="run-parent",
        step_id="step-parent",
        call_id="call-parent",
    )

    created = registry.get("create_team").run(
        {
            "workspace_id": str(workspace),
            "lead_name": "lead",
            "lead_role": "协调者",
        },
        context=context,
    )
    team_id = created["team"]["team_id"]  # type: ignore[index]
    lead_member_id = created["lead"]["member_id"]  # type: ignore[index]
    member = registry.get("add_teammate").run(
        {
            "team_id": team_id,
            "lead_member_id": lead_member_id,
            "name": "alice",
            "role": "后端开发",
            "session_id": child_session.session_id,
        },
        context=context,
    )
    registry.get("assign_team_work").run(
        {
            "team_id": team_id,
            "lead_member_id": lead_member_id,
            "assignee_member_id": member["member_id"],
            "prompt": "检查数据库迁移。",
        },
        context=context,
    )

    assert capability._member_runners[member["member_id"]].process_once() is True
    assert capability._lead_runners[lead_member_id].process_once() is True

    assert {
        "create_team",
        "add_teammate",
        "assign_team_work",
        "send_team_message",
    }.issubset(definition.name for definition in registry.list_definitions())
    assert len(thread_factory.names) == 2
    assert thread_factory.names[0].startswith("team-lead-member-")
    assert thread_factory.names[1].startswith("team-member-member-")
    assert len(model.requests) == 2
    assert model.requests[1].session_id == parent_session.session_id
    child_registry = SubagentToolRegistryFactory(registry, SubagentPolicy()).create()
    assert not {
        "create_team",
        "add_teammate",
        "assign_team_work",
        "send_team_message",
    }.intersection(definition.name for definition in child_registry.list_definitions())
    capability.stop()


def test_cli_cron_composition_runs_due_prompt_and_keeps_tools_parent_only(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = workspace / "var" / "state"
    repository = JsonFileStateRepository(state_root)
    conversation_repository = JsonFileConversationRepository(state_root)
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    catalog = _skill_catalog()
    registry = create_tool_registry(workspace, skill_catalog=catalog)
    model = FakeModel(ModelResponse.text_completion("定时检查完成。"))
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        system_prompt_provider=create_cli_system_prompt_provider(
            workspace=workspace,
            registry=registry,
            skill_catalog=catalog,
        ),
    )
    factory = InlineCronThreadFactory()
    capability = register_cli_cron_capability(
        workspace=workspace,
        registry=registry,
        session=session,
        repository=repository,
        loop=loop,
        clock=FixedCronClock(),
        scheduler_waiter=StopAfterFirstCronWait(),
        processor_waiter=StopAfterFirstCronWait(),
        thread_factory=factory,  # type: ignore[arg-type]
    )
    registry.get("schedule_cron").run(
        {"cron": "0 9 * * *", "prompt": "运行定时检查。"},
        context=ToolExecutionContext(
            session_id=session.session_id,
            run_id="run-registration",
            step_id="step-registration",
        ),
    )

    capability.start()
    capability.stop()

    request = model.requests[0]
    assert request.conversation[0].content[0].text == "运行定时检查。"
    assert {"schedule_cron", "list_crons", "cancel_cron"}.issubset(
        definition.name for definition in request.tools
    )
    child_registry = SubagentToolRegistryFactory(registry, SubagentPolicy()).create()
    assert not {"schedule_cron", "list_crons", "cancel_cron"}.intersection(
        definition.name for definition in child_registry.list_definitions()
    )
    assert factory.names == ["cron-scheduler", "cron-queue-processor"]


def test_cli_background_task_composition_continues_tools_and_delivers_notification(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = workspace / "var" / "state"
    repository = JsonFileStateRepository(state_root)
    conversation_repository = JsonFileConversationRepository(state_root)
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    background_repository = SignalingBackgroundTaskRepository()
    command_runner = CoordinatedCommandRunner()
    model = BackgroundTaskCliModel(command_runner, background_repository)
    catalog = _skill_catalog()
    registry = create_tool_registry(workspace, skill_catalog=catalog)
    notification_source = register_cli_background_task_capability(
        workspace=workspace,
        registry=registry,
        repository=background_repository,
        command_runner=command_runner,
    )
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        hook_runner=create_permission_hook_runner(workspace),
        system_prompt_provider=create_cli_system_prompt_provider(
            workspace=workspace,
            registry=registry,
            skill_catalog=catalog,
        ),
        todo_reminder_policy=TodoReminderPolicy(),
        transient_recovery_executor=create_transient_recovery_executor(
            DeepSeekSettings(
                api_key="测试密钥",
                base_url="https://example.test/anthropic",
                model="primary-model",
                max_tokens=8_000,
            )
        ),
        pending_user_message_source=notification_source,
    )

    result = execute_prompt(
        prompt="后台运行测试并继续检查文件。",
        session=session,
        repository=repository,
        loop=loop,
    )

    first_request, after_background, after_file_listing = model.requests
    assert result.response.text == "后台检查完成，已继续检查工作区。"
    assert BACKGROUND_TASK_SYSTEM_PROMPT in first_request.system_prompt  # type: ignore[operator]
    assert {"bash", "task_create", "todo_write"}.issubset(
        definition.name for definition in first_request.tools
    )
    background_result = after_background.conversation[-1].content
    assert len(background_result) == 1
    assert isinstance(background_result[0], ToolResultBlock)
    assert background_result[0].tool_use_id == "toolu-background"
    assert background_result[0].content["bg_id"] == "bg_0001"
    file_result_and_notification = after_file_listing.conversation[-1].content
    assert len(file_result_and_notification) == 2
    assert isinstance(file_result_and_notification[0], ToolResultBlock)
    assert file_result_and_notification[0].tool_use_id == "toolu-list-files"
    assert isinstance(file_result_and_notification[1], TextBlock)
    assert "<task_id>bg_0001</task_id>" in file_result_and_notification[1].text
    assert "<status>completed</status>" in file_result_and_notification[1].text
    persisted_notifications = [
        block.text
        for message in conversation_repository.get_messages(session.session_id)
        for block in message.content
        if isinstance(block, TextBlock) and "<task_notification>" in block.text
    ]
    assert len(persisted_notifications) == 1


def test_cli_composition_registers_task_system_tools_and_returns_persistent_results(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = JsonFileStateRepository(workspace / "var" / "state")
    conversation_repository = JsonFileConversationRepository(workspace / "var" / "state")
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-task-create",
                        name="task_create",
                        input={"subject": "建立表结构。"},
                    ),
                ),
            ),
            ModelResponse.text_completion("已创建并持久化任务。"),
        )
    )
    catalog = _skill_catalog()
    registry = create_tool_registry(workspace, skill_catalog=catalog)
    prompt_provider = create_cli_system_prompt_provider(
        workspace=workspace,
        registry=registry,
        skill_catalog=catalog,
    )
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        hook_runner=create_permission_hook_runner(workspace),
        system_prompt_provider=prompt_provider,
    )

    result = execute_prompt(
        prompt="请记录建立表结构这项工作。",
        session=session,
        repository=repository,
        loop=loop,
    )

    first_request, follow_up_request = model.requests
    assert result.response.text == "已创建并持久化任务。"
    assert TASK_SYSTEM_PROMPT in first_request.system_prompt  # type: ignore[operator]
    assert {
        "task_create",
        "task_list",
        "task_get",
        "task_claim",
        "task_complete",
    }.issubset(definition.name for definition in first_request.tools)
    task_result = follow_up_request.conversation[2].content[0].content
    task_id = task_result["task_id"]
    assert task_result["status"] == "pending"
    assert (workspace / "var" / "state" / "tasks" / f"{task_id}.json").is_file()


def test_cli_composition_registers_task_and_keeps_it_out_of_child_tools(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = JsonFileStateRepository(workspace / "var" / "state")
    conversation_repository = JsonFileConversationRepository(workspace / "var" / "state")
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
        created_at=timestamp,
    )
    repository.save_session(session)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-parent",
                        name="task",
                        input={"description": "调查测试框架。"},
                    ),
                ),
            ),
            ModelResponse.text_completion("子 Agent 返回 pytest。"),
            ModelResponse.text_completion("父 Agent 已验收子任务结论。"),
        )
    )
    catalog = _skill_catalog()
    registry = create_tool_registry(workspace, skill_catalog=catalog)
    register_cli_background_task_capability(
        workspace=workspace,
        registry=registry,
    )
    hook_runner = create_permission_hook_runner(workspace)
    registry.register(
        TaskTool(
            create_subagent_runner(
                repository=repository,
                conversation_repository=conversation_repository,
                model=model,
                parent_registry=registry,
                hook_runner=hook_runner,
            )
        )
    )
    prompt_provider = create_cli_system_prompt_provider(
        workspace=workspace,
        registry=registry,
        skill_catalog=catalog,
    )
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        hook_runner=hook_runner,
        system_prompt_provider=prompt_provider,
    )

    result = execute_prompt(
        prompt="请调查项目测试框架。",
        session=session,
        repository=repository,
        loop=loop,
    )

    parent_request, child_request, parent_follow_up = model.requests
    assert result.response.text == "父 Agent 已验收子任务结论。"
    assert "task" in [definition.name for definition in parent_request.tools]
    assert "compact" in [definition.name for definition in parent_request.tools]
    assert "read_artifact" in [definition.name for definition in parent_request.tools]
    assert "load_skill" in [definition.name for definition in parent_request.tools]
    assert "bash" in [definition.name for definition in parent_request.tools]
    assert "task" not in [definition.name for definition in child_request.tools]
    assert "task_create" not in [definition.name for definition in child_request.tools]
    assert "task_list" not in [definition.name for definition in child_request.tools]
    assert "task_get" not in [definition.name for definition in child_request.tools]
    assert "task_claim" not in [definition.name for definition in child_request.tools]
    assert "task_complete" not in [definition.name for definition in child_request.tools]
    assert "todo_write" not in [definition.name for definition in child_request.tools]
    assert "load_skill" not in [definition.name for definition in child_request.tools]
    assert "compact" not in [definition.name for definition in child_request.tools]
    assert "read_artifact" not in [definition.name for definition in child_request.tools]
    assert "bash" not in [definition.name for definition in child_request.tools]
    assert child_request.system_prompt != prompt_provider.get_system_prompt()
    assert parent_follow_up.conversation[2].content[0].content["summary"] == (
        "子 Agent 返回 pytest。"
    )


def test_cli_skill_tool_result_is_returned_to_the_next_parent_model_request(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = JsonFileStateRepository(workspace / "var" / "state")
    conversation_repository = JsonFileConversationRepository(workspace / "var" / "state")
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-skill",
                        name="load_skill",
                        input={"name": "code-review"},
                    ),
                ),
            ),
            ModelResponse.text_completion("已根据代码审查技能完成检查。"),
        )
    )
    catalog = _skill_catalog()
    registry = create_tool_registry(workspace, skill_catalog=catalog)
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        hook_runner=create_permission_hook_runner(workspace),
        system_prompt_provider=create_cli_system_prompt_provider(
            workspace=workspace,
            registry=registry,
            skill_catalog=catalog,
        ),
    )

    result = execute_prompt(
        prompt="请审查当前代码。",
        session=session,
        repository=repository,
        loop=loop,
    )

    first_request, follow_up_request = model.requests
    assert result.response.text == "已根据代码审查技能完成检查。"
    assert "完整技能正文" not in first_request.system_prompt
    assert follow_up_request.conversation[2].content[0].content["content"] == (
        "---\nname: code-review\n---\n# 完整技能正文\n"
    )
