"""把 Team 成员输入交给既有 Runtime 状态编排和 Agent Loop 的适配器。"""

from __future__ import annotations

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService

from .schema import TeamMember, TeamPromptExecution


class RuntimeTeamAgentExecutor:
    """复用已有 Run、权限、Hook 与 Transcript 边界执行 Team 成员输入。"""

    def __init__(
        self,
        *,
        runtime_service: UserInputRuntimeService,
        loop: MinimalAgentLoop,
    ) -> None:
        if not callable(getattr(runtime_service, "handle", None)):
            raise TypeError("runtime_service 必须提供 handle 方法。")
        if not callable(getattr(loop, "execute", None)):
            raise TypeError("loop 必须提供 execute 方法。")
        self._runtime_service = runtime_service
        self._loop = loop

    def execute(
        self,
        *,
        member: TeamMember,
        prompt: str,
    ) -> TeamPromptExecution:
        """创建该成员 Session 的独立 Run，并返回真实 Run 与最终响应关联。"""

        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 必须是非空字符串。")
        start = self._runtime_service.handle(
            UserInputEvent.create(session_id=member.session_id, content=prompt)
        )
        result = self._loop.execute(start)
        response_text = result.response.text
        if not isinstance(response_text, str):
            raise TypeError("Agent Loop 响应文本必须是字符串。")
        return TeamPromptExecution(
            session_id=member.session_id,
            run_id=result.run.run_id,
            response_text=response_text,
        )
