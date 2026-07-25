"""本地 Agent 的最小交互式启动入口。"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookEvent, HookRegistry, HookRunner
from local_dev_agent.models import DeepSeekAnthropicModelClient, DeepSeekSettings, ModelClient
from local_dev_agent.observability import configure_logging
from local_dev_agent.permissions import PermissionHook, SimplePermissionPolicy
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.runtime.loop import AgentLoopResult
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.ports import StateRepository
from local_dev_agent.todos import JsonFileTodoRepository
from local_dev_agent.tools import ToolRegistry
from local_dev_agent.tools.builtin import (
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    TodoWriteTool,
    WriteFileTool,
)


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


def create_tool_registry(workspace: Path) -> ToolRegistry:
    """组装 CLI 默认可用的低风险工具，避免入口直接依赖工具细节。"""

    registry = ToolRegistry()
    registry.register(ListFilesTool(workspace))
    registry.register(ReadFileTool(workspace))
    registry.register(WriteFileTool(workspace))
    registry.register(EditFileTool(workspace))
    registry.register(
        TodoWriteTool(JsonFileTodoRepository(workspace / "var" / "state" / "todos"))
    )
    return registry


def create_permission_hook_runner(workspace: Path) -> HookRunner:
    """组装 learnClaudeCode S3 风格的默认执行前权限检查。"""

    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        PermissionHook(SimplePermissionPolicy(workspace)),
    )
    return HookRunner(registry)


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
    model: ModelClient = DeepSeekAnthropicModelClient(
        DeepSeekSettings.from_environment()
    )
    tool_registry = create_tool_registry(workspace)
    loop = MinimalAgentLoop(
        repository,
        model,
        tool_registry,
        conversation_repository,
        hook_runner=create_permission_hook_runner(workspace),
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
