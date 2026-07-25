"""同步执行、上下文隔离的子 Agent 运行器。"""

from __future__ import annotations

import logging

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookRunner
from local_dev_agent.models import ModelClient
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.runtime.errors import AgentLoopExhaustedError
from local_dev_agent.storage.conversation_ports import ConversationRepository
from local_dev_agent.storage.ports import StateRepository

from .errors import SubagentParentSessionNotFoundError
from .schema import SubagentOutcome, SubagentResult, SubagentTask
from .tool_registry import SubagentToolRegistryFactory

logger = logging.getLogger(__name__)


class SynchronousSubagentRunner:
    """为一项任务创建隔离子会话，并同步返回其最小结构化结论。"""

    def __init__(
        self,
        repository: StateRepository,
        conversation_repository: ConversationRepository,
        model: ModelClient,
        tool_registry_factory: SubagentToolRegistryFactory,
        *,
        hook_runner: HookRunner | None = None,
    ) -> None:
        if not isinstance(tool_registry_factory, SubagentToolRegistryFactory):
            raise TypeError("子 Agent 工具目录工厂必须是 SubagentToolRegistryFactory 对象。")
        self._repository = repository
        self._conversation_repository = conversation_repository
        self._model = model
        self._tool_registry_factory = tool_registry_factory
        self._hook_runner = hook_runner

    def run(self, task: SubagentTask) -> SubagentResult:
        """使用全新 Session 和 Transcript 执行任务，只返回最终结构化结果。"""

        if not isinstance(task, SubagentTask):
            raise TypeError("子 Agent 运行器只能执行 SubagentTask 对象。")
        parent_session = self._repository.get_session(task.parent_session_id)
        if parent_session is None:
            raise SubagentParentSessionNotFoundError(session_id=task.parent_session_id)

        child_session = self._create_child_session(parent_session)
        self._repository.save_session(child_session)
        event = UserInputEvent.create(
            session_id=child_session.session_id,
            content=self._task_prompt(task),
        )
        start = UserInputRuntimeService(self._repository).handle(event)
        policy = self._tool_registry_factory.policy
        loop = MinimalAgentLoop(
            self._repository,
            self._model,
            self._tool_registry_factory.create(),
            self._conversation_repository,
            max_turns=policy.max_turns,
            hook_runner=self._hook_runner,
            system_prompt=policy.system_prompt,
        )
        log_context = {
            "task_id": task.task_id,
            "parent_session_id": task.parent_session_id,
            "parent_run_id": task.parent_run_id,
            "parent_step_id": task.parent_step_id,
            "session_id": child_session.session_id,
            "run_id": start.run.run_id,
        }
        logger.info("子 Agent 开始同步执行。", extra=log_context)
        try:
            loop_result = loop.execute(start)
        except AgentLoopExhaustedError as error:
            logger.warning("子 Agent 已耗尽模型调用轮次。", extra=log_context)
            return SubagentResult.create(
                task_id=task.task_id,
                outcome=SubagentOutcome.EXHAUSTED,
                summary=str(error),
                child_session_id=child_session.session_id,
                child_run_id=start.run.run_id,
            )

        logger.info("子 Agent 已完成同步执行。", extra=log_context)
        return SubagentResult.create(
            task_id=task.task_id,
            outcome=SubagentOutcome.SUCCEEDED,
            summary=loop_result.response.text,
            child_session_id=loop_result.session.session_id,
            child_run_id=loop_result.run.run_id,
        )

    @staticmethod
    def _create_child_session(parent_session: SessionState) -> SessionState:
        """仅复制身份与项目边界，不复制父会话状态或消息历史。"""

        return SessionState.create(
            tenant_id=parent_session.tenant_id,
            user_id=parent_session.user_id,
            project_id=parent_session.project_id,
        )

    @staticmethod
    def _task_prompt(task: SubagentTask) -> str:
        """仅向子上下文传入任务和显式验收标准，避免泄漏父对话。"""

        if not task.acceptance_criteria:
            return task.description
        criteria = "\n".join(f"- {item}" for item in task.acceptance_criteria)
        return f"{task.description}\n\n验收标准：\n{criteria}"
