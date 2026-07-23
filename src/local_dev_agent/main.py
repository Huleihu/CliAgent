"""本地 Agent 的最小交互式启动入口。"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.models import DeepSeekAnthropicModelClient, DeepSeekSettings, ModelClient
from local_dev_agent.observability import configure_logging
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.runtime.loop import AgentLoopResult
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.storage.ports import StateRepository
from local_dev_agent.tools import ToolRegistry


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


def main() -> None:
    """启动交互式 Demo：每条输入创建一个 Run，并打印最终文本。"""

    load_dotenv()
    workspace = Path.cwd().resolve()
    configure_logging(log_directory=workspace / "var" / "logs")
    repository = JsonFileStateRepository(workspace / "var" / "state")
    session = SessionState.create(
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    model: ModelClient = DeepSeekAnthropicModelClient(
        DeepSeekSettings.from_environment()
    )
    loop = MinimalAgentLoop(repository, model, ToolRegistry())

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
