"""只处理纯文本完成路径的最小 Agent Loop。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from local_dev_agent.domain.state import RunState, RunStatus, SessionState, StepState, StepStatus
from local_dev_agent.models import ModelClient, ModelRequest, ModelResponse
from local_dev_agent.storage.ports import StateRepository

from .input_service import RuntimeStartResult


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    """纯文本执行路径结束后可交给调用方渲染的结果。"""

    session: SessionState
    run: RunState
    step: StepState
    response: ModelResponse


class MinimalAgentLoop:
    """驱动单个规划步骤完成一次确定性纯文本模型调用。"""

    def __init__(self, repository: StateRepository, model: ModelClient) -> None:
        self._repository = repository
        self._model = model

    def execute(
        self,
        start: RuntimeStartResult,
        *,
        occurred_at: datetime | None = None,
    ) -> AgentLoopResult:
        """推进 Run 与 Step，调用模型并在成功后释放会话的活跃 Run。"""

        timestamp = occurred_at or datetime.now(timezone.utc)
        recovering_run = start.run.transition_to(
            RunStatus.RECOVERING,
            occurred_at=timestamp,
        )
        self._repository.save_run(recovering_run)

        running_run = recovering_run.transition_to(
            RunStatus.RUNNING,
            occurred_at=timestamp,
        )
        self._repository.save_run(running_run)

        executing_step = start.first_step.transition_to(
            StepStatus.EXECUTING,
            occurred_at=timestamp,
        )
        self._repository.save_step(executing_step)

        response = self._model.generate(
            ModelRequest(
                session_id=start.session.session_id,
                run_id=running_run.run_id,
                user_input=start.event.content,
            )
        )

        succeeded_step = executing_step.transition_to(
            StepStatus.SUCCEEDED,
            occurred_at=timestamp,
        )
        self._repository.save_step(succeeded_step)

        completed_run = running_run.transition_to(
            RunStatus.COMPLETED,
            occurred_at=timestamp,
        )
        self._repository.save_run(completed_run)

        available_session = start.session.finish_run(
            completed_run.run_id,
            occurred_at=timestamp,
        )
        self._repository.save_session(available_session)

        return AgentLoopResult(
            session=available_session,
            run=completed_run,
            step=succeeded_step,
            response=response,
        )
