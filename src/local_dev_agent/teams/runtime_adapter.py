"""把 Team 成员输入交给既有 Runtime 状态编排和 Agent Loop 的适配器。"""

from __future__ import annotations

from pathlib import Path

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.tools.ports import RunWorkingDirectoryRegistry

from .schema import TeamMember, TeamPromptExecution


class RuntimeTeamAgentExecutor:
    """复用已有 Run、权限、Hook 与 Transcript 边界执行 Team 成员输入。"""

    def __init__(
        self,
        *,
        runtime_service: UserInputRuntimeService,
        loop: MinimalAgentLoop,
        run_working_directory_registry: RunWorkingDirectoryRegistry | None = None,
    ) -> None:
        if not callable(getattr(runtime_service, "handle", None)):
            raise TypeError("runtime_service 必须提供 handle 方法。")
        if not callable(getattr(loop, "execute", None)):
            raise TypeError("loop 必须提供 execute 方法。")
        if run_working_directory_registry is not None and not all(
            callable(getattr(run_working_directory_registry, method_name, None))
            for method_name in ("bind", "release")
        ):
            raise TypeError("run_working_directory_registry 必须提供 bind 和 release 方法或为 None。")
        self._runtime_service = runtime_service
        self._loop = loop
        self._run_working_directory_registry = run_working_directory_registry

    def execute(
        self,
        *,
        member: TeamMember,
        prompt: str,
        working_directory: Path | None = None,
    ) -> TeamPromptExecution:
        """创建该成员 Session 的独立 Run，并返回真实 Run 与最终响应关联。"""

        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 必须是非空字符串。")
        if working_directory is not None and not isinstance(working_directory, Path):
            raise TypeError("working_directory 必须是 Path 对象或 None。")
        start = self._runtime_service.handle(
            UserInputEvent.create(session_id=member.session_id, content=prompt)
        )
        if working_directory is None:
            result = self._loop.execute(start)
        else:
            if self._run_working_directory_registry is None:
                raise RuntimeError("成员 Run 指定工作目录时必须配置目录注册表。")
            run_id = start.run.run_id
            self._run_working_directory_registry.bind(
                run_id=run_id,
                directory=working_directory,
            )
            try:
                result = self._loop.execute(start)
            finally:
                self._run_working_directory_registry.release(run_id=run_id)
        response_text = result.response.text
        if not isinstance(response_text, str):
            raise TypeError("Agent Loop 响应文本必须是字符串。")
        return TeamPromptExecution(
            session_id=member.session_id,
            run_id=result.run.run_id,
            response_text=response_text,
        )
