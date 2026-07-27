"""本地 Agent 的最小交互式启动入口。"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from local_dev_agent.context import (
    ContextBudget,
    ContextManager,
    FileSystemToolResultArtifactStore,
    HistorySummaryCompactor,
    ModelConversationSummarizer,
    ToolResultBudgetCompactor,
)
from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookEvent, HookRegistry, HookRunner
from local_dev_agent.models import DeepSeekAnthropicModelClient, DeepSeekSettings, ModelClient
from local_dev_agent.observability import configure_logging
from local_dev_agent.permissions import PermissionHook, SimplePermissionPolicy
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.runtime.loop import AgentLoopResult
from local_dev_agent.skills import (
    FileSystemSkillCatalogLoader,
    SkillCatalog,
    format_skill_catalog,
)
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.conversation_ports import ConversationRepository
from local_dev_agent.storage.ports import StateRepository
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
    TaskTool,
    TodoWriteTool,
    WriteFileTool,
)


TODO_PLANNING_SYSTEM_PROMPT = """你是本地开发 Agent。

处理包含多个步骤的任务时，先使用 todo_write 创建完整待办清单。开始事项时将其标记为 in_progress；完成并验证后标记为 completed。简单的单步骤任务无需创建待办清单。"""


TASK_DELEGATION_SYSTEM_PROMPT = """对于需要独立调查、实现或验证的有界复杂子任务，可使用 task 委派给子 Agent。

task 只返回结构化结论和关联信息；收到结果后由你验收结论，并在需要时自行验证共享工作区中的副作用。简单任务不要委派。"""

CONTEXT_COMPACTION_SYSTEM_PROMPT = """当当前历史已冗余或需要切换任务时，可调用 compact 请求 Runtime 在下一轮压缩上下文。

compact 不会修改完整会话历史；不要把它当作文件或消息编辑工具。"""


CLI_SYSTEM_PROMPT = (
    TODO_PLANNING_SYSTEM_PROMPT
    + "\n\n"
    + TASK_DELEGATION_SYSTEM_PROMPT
    + "\n\n"
    + CONTEXT_COMPACTION_SYSTEM_PROMPT
)

CLI_CONTEXT_WINDOW_TOKENS = 128_000
"""CLI 首版使用的显式上下文窗口预算，后续可由模型配置替换。"""

CLI_CONTEXT_SAFETY_MARGIN_TOKENS = 13_000
"""为 Provider 格式化差异和最终输出保留的保守余量。"""


def build_cli_system_prompt(skill_catalog: SkillCatalog) -> str:
    """组合稳定 CLI 指导和仅含元数据的启动时技能目录。"""

    return CLI_SYSTEM_PROMPT + "\n\n" + format_skill_catalog(skill_catalog)


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

    return ContextManager(
        ContextBudget(
            context_window_tokens=CLI_CONTEXT_WINDOW_TOKENS,
            max_output_tokens=max_output_tokens,
            safety_margin_tokens=CLI_CONTEXT_SAFETY_MARGIN_TOKENS,
        ),
        ToolResultBudgetCompactor(
            FileSystemToolResultArtifactStore(workspace / "var" / "artifacts")
        ),
        HistorySummaryCompactor(ModelConversationSummarizer(model)),
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
        system_prompt=build_cli_system_prompt(skill_catalog),
        todo_reminder_policy=TodoReminderPolicy(),
        context_manager=create_context_manager(
            workspace=workspace,
            model=model,
            max_output_tokens=settings.max_tokens,
        ),
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
