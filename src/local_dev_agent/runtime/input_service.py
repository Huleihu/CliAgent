"""将用户输入事件编排为最小运行状态骨架。"""

from __future__ import annotations

from dataclasses import dataclass

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import RunState, SessionState, StepState, StepType
from local_dev_agent.storage.ports import StateRepository

from .errors import SessionNotFoundError


@dataclass(frozen=True, slots=True)
class RuntimeStartResult:
    """处理用户输入后产生、已保存的状态快照集合。"""

    event: UserInputEvent
    session: SessionState
    run: RunState
    first_step: StepState


class UserInputRuntimeService:
    """为用户输入创建 Run 与首个规划 Step 的最小应用服务。"""

    def __init__(self, repository: StateRepository) -> None:
        self._repository = repository

    def handle(self, event: UserInputEvent) -> RuntimeStartResult:
        """消费输入事件，创建并持久化一轮尚未执行的运行。"""

        session = self._repository.get_session(event.session_id)
        if session is None:
            raise SessionNotFoundError(session_id=event.session_id)

        run = RunState.create(session_id=session.session_id, created_at=event.occurred_at)
        first_step = StepState.create(
            run_id=run.run_id,
            step_type=StepType.PLAN,
            created_at=event.occurred_at,
        )
        active_session = session.start_run(run.run_id, occurred_at=event.occurred_at)

        # 先保存被会话引用的子对象，避免成功快照指向尚未落盘的对象。
        self._repository.save_run(run)
        self._repository.save_step(first_step)
        self._repository.save_session(active_session)

        return RuntimeStartResult(
            event=event,
            session=active_session,
            run=run,
            first_step=first_step,
        )
