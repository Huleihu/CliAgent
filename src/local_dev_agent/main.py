"""本地 Agent 的最小交互式启动入口。"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

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
from local_dev_agent.todos import JsonFileTodoRepository, TodoReminderPolicy
from local_dev_agent.tools import ToolRegistry
from local_dev_agent.tools.builtin import (
    CompactContextTool,
    EditFileTool,
    ListFilesTool,
    LoadSkillTool,
    ReadFileTool,
    ReadArtifactTool,
    TaskTool,
    TodoWriteTool,
    WriteFileTool,
)


CLI_CONTEXT_WINDOW_TOKENS = 128_000
"""CLI 首版使用的显式上下文窗口预算，后续可由模型配置替换。"""

CLI_CONTEXT_SAFETY_MARGIN_TOKENS = 13_000
"""为 Provider 格式化差异和最终输出保留的保守余量。"""

CLI_HISTORY_SUMMARY_CHECKPOINT_TAIL_MESSAGE_COUNT = 10
"""重建历史摘要检查点时保留的最近原始消息数量。"""


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
    if skill_catalog is not None:
        registry.register(LoadSkillTool(skill_catalog))
    return registry


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
    tool_registry = create_tool_registry(workspace, skill_catalog=skill_catalog)
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
    )

    print("Local Dev Agent")
    print("输入问题并回车发送。输入 q、exit 或空行退出。\n")
    while True:
        try:
            prompt = input("local-dev-agent >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if prompt.lower() in {"", "q", "exit"}:
            return

        result = execute_prompt(
            prompt=prompt,
            session=session,
            repository=repository,
            loop=loop,
        )
        session = result.session
        print(result.response.text)
        print()


if __name__ == "__main__":
    main()
