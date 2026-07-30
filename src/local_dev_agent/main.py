"""本地 Agent 的最小交互式启动入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from local_dev_agent.background_tasks import (
    BackgroundTaskIdGenerator,
    BackgroundTaskNotificationSource,
    BackgroundTaskRepository,
    CommandRunner,
    InMemoryBackgroundTaskRepository,
    SequentialBackgroundTaskIdGenerator,
    SubprocessCommandRunner,
    ThreadedBackgroundTaskService,
)
from local_dev_agent.context import (
    ContextBudget,
    ContextManager,
    FileSystemToolResultArtifactStore,
    FullHistorySummaryCheckpointRebuilder,
    HistorySummaryCompactor,
    HistorySummaryCheckpointService,
    ModelConversationSummarizer,
    ToolResultBudgetCompactor,
)
from local_dev_agent.cron import (
    CronClock,
    CronQueueProcessor,
    CronQueueProcessorRunner,
    CronScheduler,
    CronSchedulerRunner,
    CronThreadFactory,
    CronWaiter,
    CronTaskCatalog,
    CronTaskService,
    DaemonCronThreadFactory,
    EventCronWaiter,
    InMemoryCronTaskRepository,
    InMemoryCronTriggerQueue,
    JsonFileCronTaskRepository,
    LockCronExecutionGate,
    SessionBoundCronTriggerConsumer,
    SystemCronClock,
    UuidCronTaskIdGenerator,
)
from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookEvent, HookRegistry, HookRunner
from local_dev_agent.models import DeepSeekAnthropicModelClient, DeepSeekSettings, ModelClient
from local_dev_agent.memory import (
    FileSystemMemoryRepository,
    MemoryExtractionService,
    MemoryConsolidationService,
    MemoryLoader,
    ModelMemoryExtractor,
    ModelMemoryConsolidator,
    ModelMemorySelector,
)
from local_dev_agent.observability import configure_logging
from local_dev_agent.permissions import PermissionHook, SimplePermissionPolicy
from local_dev_agent.recovery import (
    OutputBudgetUpgradePolicy,
    OutputContinuationPolicy,
    TransientModelRecoveryExecutor,
    TransientRecoveryPolicy,
)
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.runtime.loop import AgentLoopResult
from local_dev_agent.skills import (
    FileSystemSkillCatalogLoader,
    SkillCatalog,
)
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.json_history_summary_checkpoint_repository import (
    JsonFileHistorySummaryCheckpointRepository,
)
from local_dev_agent.storage.conversation_ports import ConversationRepository
from local_dev_agent.storage.ports import StateRepository
from local_dev_agent.system_prompt import create_cli_system_prompt_provider
from local_dev_agent.subagents import (
    SubagentPolicy,
    SubagentToolRegistryFactory,
    SynchronousSubagentRunner,
)
from local_dev_agent.tasks import (
    JsonFileTaskRepository,
    TaskService,
    UuidTaskIdGenerator,
)
from local_dev_agent.todos import JsonFileTodoRepository, TodoReminderPolicy
from local_dev_agent.tools import ToolRegistry
from local_dev_agent.tools.builtin import (
    BashTool,
    CompactContextTool,
    EditFileTool,
    ListFilesTool,
    LoadSkillTool,
    ReadFileTool,
    ReadArtifactTool,
    ScheduleCronTool,
    ListCronsTool,
    CancelCronTool,
    TaskTool,
    TaskClaimTool,
    TaskCompleteTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TodoWriteTool,
    WriteFileTool,
)


CLI_CONTEXT_WINDOW_TOKENS = 128_000
"""CLI 首版使用的显式上下文窗口预算，后续可由模型配置替换。"""

CLI_CONTEXT_SAFETY_MARGIN_TOKENS = 13_000
"""为 Provider 格式化差异和最终输出保留的保守余量。"""

CLI_HISTORY_SUMMARY_CHECKPOINT_TAIL_MESSAGE_COUNT = 10
"""重建历史摘要检查点时保留的最近原始消息数量。"""


@dataclass(slots=True)
class CliCronCapability:
    """CLI 持有的 Cron 生命周期与共享 Agent 执行租约。"""

    execution_gate: LockCronExecutionGate
    scheduler_runner: CronSchedulerRunner
    processor_runner: CronQueueProcessorRunner

    def start(self) -> None:
        """启动彼此独立的调度和队列处理 daemon 线程。"""

        self.scheduler_runner.start()
        self.processor_runner.start()

    def stop(self) -> None:
        """请求两个 daemon 线程停止，不阻塞 CLI 的退出路径。"""

        self.scheduler_runner.stop()
        self.processor_runner.stop()


def execute_prompt(
    *,
    prompt: str,
    session: SessionState,
    repository: StateRepository,
    loop: MinimalAgentLoop,
) -> AgentLoopResult:
    """将一条终端输入编排为 Run，再交给 Agent Loop 执行。"""

    event = UserInputEvent.create(session_id=session.session_id, content=prompt)
    start = UserInputRuntimeService(repository).handle(event)
    return loop.execute(start)


def create_tool_registry(
    workspace: Path,
    *,
    skill_catalog: SkillCatalog | None = None,
    task_service: TaskService | None = None,
) -> ToolRegistry:
    """组装 CLI 默认可用的低风险工具，避免入口直接依赖工具细节。"""

    registry = ToolRegistry()
    registry.register(ListFilesTool(workspace))
    registry.register(ReadFileTool(workspace))
    registry.register(WriteFileTool(workspace))
    registry.register(EditFileTool(workspace))
    registry.register(CompactContextTool())
    registry.register(
        ReadArtifactTool(FileSystemToolResultArtifactStore(workspace / "var" / "artifacts"))
    )
    registry.register(
        TodoWriteTool(JsonFileTodoRepository(workspace / "var" / "state" / "todos"))
    )
    active_task_service = task_service or create_task_service(workspace)
    registry.register(TaskCreateTool(active_task_service))
    registry.register(TaskListTool(active_task_service))
    registry.register(TaskGetTool(active_task_service))
    registry.register(TaskClaimTool(active_task_service))
    registry.register(TaskCompleteTool(active_task_service))
    if skill_catalog is not None:
        registry.register(LoadSkillTool(skill_catalog))
    return registry


def create_task_service(workspace: Path) -> TaskService:
    """组装工作区级任务图服务，任务文件独立于会话与 Todo 清单。"""

    return TaskService(
        JsonFileTaskRepository(workspace / "var" / "state" / "tasks"),
        UuidTaskIdGenerator(),
    )


def register_cli_background_task_capability(
    *,
    workspace: Path,
    registry: ToolRegistry,
    repository: BackgroundTaskRepository | None = None,
    id_generator: BackgroundTaskIdGenerator | None = None,
    command_runner: CommandRunner | None = None,
) -> BackgroundTaskNotificationSource:
    """组装父侧后台命令能力，并让工具与通知共享同一进程内仓储。"""

    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry 必须是 ToolRegistry 对象。")
    active_repository = (
        repository if repository is not None else InMemoryBackgroundTaskRepository()
    )
    active_id_generator = (
        id_generator
        if id_generator is not None
        else SequentialBackgroundTaskIdGenerator()
    )
    active_command_runner = (
        command_runner if command_runner is not None else SubprocessCommandRunner()
    )
    service = ThreadedBackgroundTaskService(
        active_repository,
        active_id_generator,
        active_command_runner,
    )
    registry.register(
        BashTool(
            workspace,
            active_command_runner,
            service,
        )
    )
    return BackgroundTaskNotificationSource(active_repository)


def register_cli_cron_capability(
    *,
    workspace: Path,
    registry: ToolRegistry,
    session: SessionState,
    repository: StateRepository,
    loop: MinimalAgentLoop,
    clock: CronClock | None = None,
    scheduler_waiter: CronWaiter | None = None,
    processor_waiter: CronWaiter | None = None,
    thread_factory: CronThreadFactory | None = None,
) -> CliCronCapability:
    """装配父侧 Cron 工具和两条后台线程，不让 Cron 领域依赖 Runtime。"""

    if not isinstance(workspace, Path):
        raise TypeError("workspace 必须是 Path 对象。")
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry 必须是 ToolRegistry 对象。")
    if not isinstance(session, SessionState):
        raise TypeError("session 必须是 SessionState 对象。")
    active_clock = clock if clock is not None else SystemCronClock()
    active_session_repository = InMemoryCronTaskRepository()
    active_durable_repository = JsonFileCronTaskRepository(
        workspace / "var" / "state" / "cron"
    )
    service = CronTaskService(
        session_repository=active_session_repository,
        durable_repository=active_durable_repository,
        id_generator=UuidCronTaskIdGenerator(),
        clock=active_clock,
    )
    registry.register(ScheduleCronTool(service))
    registry.register(ListCronsTool(service))
    registry.register(CancelCronTool(service))

    trigger_queue = InMemoryCronTriggerQueue()
    execution_gate = LockCronExecutionGate()

    def run_scheduled_prompt(prompt: str) -> None:
        result = execute_prompt(
            prompt=prompt,
            session=session,
            repository=repository,
            loop=loop,
        )
        print(f"\n[cron] {result.response.text}")

    consumer = SessionBoundCronTriggerConsumer(
        session_id=session.session_id,
        run_prompt=run_scheduled_prompt,
    )
    scheduler = CronScheduler(
        repository=CronTaskCatalog(
            session_repository=active_session_repository,
            durable_repository=active_durable_repository,
        ),
        trigger_queue=trigger_queue,
        clock=active_clock,
        session_id=session.session_id,
    )
    processor = CronQueueProcessor(
        trigger_queue=trigger_queue,
        gate=execution_gate,
        consumer=consumer,
    )
    active_thread_factory = (
        thread_factory if thread_factory is not None else DaemonCronThreadFactory()
    )
    return CliCronCapability(
        execution_gate=execution_gate,
        scheduler_runner=CronSchedulerRunner(
            scheduler=scheduler,
            waiter=scheduler_waiter if scheduler_waiter is not None else EventCronWaiter(),
            thread_factory=active_thread_factory,
        ),
        processor_runner=CronQueueProcessorRunner(
            processor=processor,
            waiter=processor_waiter if processor_waiter is not None else EventCronWaiter(),
            thread_factory=active_thread_factory,
        ),
    )


def create_permission_hook_runner(workspace: Path) -> HookRunner:
    """组装 learnClaudeCode S3 风格的默认执行前权限检查。"""

    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        PermissionHook(SimplePermissionPolicy(workspace)),
    )
    return HookRunner(registry)


def create_context_manager(
    *,
    workspace: Path,
    model: ModelClient,
    max_output_tokens: int,
) -> ContextManager:
    """组装 S8 上下文管线，保持完整 Transcript 与模型请求视图分离。"""

    summarizer = ModelConversationSummarizer(model)
    return ContextManager(
        ContextBudget(
            context_window_tokens=CLI_CONTEXT_WINDOW_TOKENS,
            max_output_tokens=max_output_tokens,
            safety_margin_tokens=CLI_CONTEXT_SAFETY_MARGIN_TOKENS,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(workspace / "var" / "artifacts")
        ),
        HistorySummaryCompactor(summarizer),
        history_summary_checkpoint_service=HistorySummaryCheckpointService(
            JsonFileHistorySummaryCheckpointRepository(workspace / "var" / "state"),
            FullHistorySummaryCheckpointRebuilder(summarizer),
        ),
        checkpoint_tail_message_count=CLI_HISTORY_SUMMARY_CHECKPOINT_TAIL_MESSAGE_COUNT,
    )


def create_transient_recovery_executor(
    settings: DeepSeekSettings,
) -> TransientModelRecoveryExecutor:
    """组装父 Agent 的 S11 瞬态故障恢复，不影响受限子 Agent。"""

    return TransientModelRecoveryExecutor(
        TransientRecoveryPolicy(fallback_model_id=settings.fallback_model),
        primary_model_id=settings.model,
    )


def create_output_budget_upgrade_policy(
    settings: DeepSeekSettings,
) -> OutputBudgetUpgradePolicy:
    """组装父 Agent 首次输出截断的固定预算升级，保留子 Agent 隔离。"""

    return OutputBudgetUpgradePolicy(initial_max_output_tokens=settings.max_tokens)


def create_output_continuation_policy() -> OutputContinuationPolicy:
    """组装父 Agent 的有界临时纯文本续写策略。"""

    return OutputContinuationPolicy()


def create_memory_loader(*, workspace: Path, model: ModelClient) -> MemoryLoader:
    """组装工作区级长期记忆加载器；目录为空时不会发起选择模型调用。"""

    return MemoryLoader(
        FileSystemMemoryRepository(workspace / "var" / "memory"),
        ModelMemorySelector(model),
    )


def create_memory_extraction_service(
    *,
    workspace: Path,
    model: ModelClient,
) -> MemoryExtractionService:
    """组装父 Agent 正常结束后使用的长期记忆提取服务。"""

    return MemoryExtractionService(
        FileSystemMemoryRepository(workspace / "var" / "memory"),
        ModelMemoryExtractor(model),
    )


def create_memory_consolidation_service(*, workspace: Path, model: ModelClient) -> MemoryConsolidationService:
    """组装按数量阈值低频触发的工作区长期记忆整理服务。"""

    return MemoryConsolidationService(
        FileSystemMemoryRepository(workspace / "var" / "memory"),
        ModelMemoryConsolidator(model),
    )


def create_subagent_runner(
    *,
    repository: StateRepository,
    conversation_repository: ConversationRepository,
    model: ModelClient,
    parent_registry: ToolRegistry,
    hook_runner: HookRunner,
) -> SynchronousSubagentRunner:
    """组装受限同步子 Agent，复用本地状态、模型和权限执行边界。"""

    policy = SubagentPolicy()
    tool_registry_factory = SubagentToolRegistryFactory(parent_registry, policy)
    return SynchronousSubagentRunner(
        repository,
        conversation_repository,
        model,
        tool_registry_factory,
        hook_runner=hook_runner,
    )


def default_workspace() -> Path:
    """返回项目内固定的演示工作区，避免终端当前目录改变工具边界。"""

    project_root = Path(__file__).resolve().parents[2]
    return (project_root / "sandbox").resolve()


def main() -> None:
    """启动交互式 Demo：每条输入创建一个 Run，并打印最终文本。"""

    load_dotenv()
    workspace = default_workspace()
    configure_logging(log_directory=workspace / "var" / "logs")
    repository = JsonFileStateRepository(workspace / "var" / "state")
    conversation_repository = JsonFileConversationRepository(workspace / "var" / "state")
    session = SessionState.create(
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    settings = DeepSeekSettings.from_environment()
    model: ModelClient = DeepSeekAnthropicModelClient(settings)
    skill_catalog = FileSystemSkillCatalogLoader(workspace).load()
    task_service = create_task_service(workspace)
    tool_registry = create_tool_registry(
        workspace,
        skill_catalog=skill_catalog,
        task_service=task_service,
    )
    background_task_notifications = register_cli_background_task_capability(
        workspace=workspace,
        registry=tool_registry,
    )
    hook_runner = create_permission_hook_runner(workspace)
    subagent_runner = create_subagent_runner(
        repository=repository,
        conversation_repository=conversation_repository,
        model=model,
        parent_registry=tool_registry,
        hook_runner=hook_runner,
    )
    tool_registry.register(TaskTool(subagent_runner))
    loop = MinimalAgentLoop(
        repository,
        model,
        tool_registry,
        conversation_repository,
        hook_runner=hook_runner,
        system_prompt_provider=create_cli_system_prompt_provider(
            workspace=workspace,
            registry=tool_registry,
            skill_catalog=skill_catalog,
        ),
        todo_reminder_policy=TodoReminderPolicy(),
        context_manager=create_context_manager(
            workspace=workspace,
            model=model,
            max_output_tokens=settings.max_tokens,
        ),
        memory_loader=create_memory_loader(workspace=workspace, model=model),
        memory_extraction_service=create_memory_extraction_service(
            workspace=workspace,
            model=model,
        ),
        memory_consolidation_service=create_memory_consolidation_service(
            workspace=workspace,
            model=model,
        ),
        transient_recovery_executor=create_transient_recovery_executor(settings),
        output_budget_upgrade_policy=create_output_budget_upgrade_policy(settings),
        output_continuation_policy=create_output_continuation_policy(),
        pending_user_message_source=background_task_notifications,
    )
    cron_capability = register_cli_cron_capability(
        workspace=workspace,
        registry=tool_registry,
        session=session,
        repository=repository,
        loop=loop,
    )
    cron_capability.start()

    print("Local Dev Agent")
    print("输入问题并回车发送。输入 q、exit 或空行退出。\n")
    try:
        while True:
            try:
                prompt = input("local-dev-agent >> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if prompt.lower() in {"", "q", "exit"}:
                return

            cron_capability.execution_gate.acquire()
            try:
                result = execute_prompt(
                    prompt=prompt,
                    session=session,
                    repository=repository,
                    loop=loop,
                )
            finally:
                cron_capability.execution_gate.release()
            session = result.session
            print(result.response.text)
            print()
    finally:
        cron_capability.stop()


if __name__ == "__main__":
    main()
