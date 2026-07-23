"""状态存取的稳定端口定义。"""

from collections.abc import Sequence
from typing import Protocol

from local_dev_agent.domain.state import RunState, SessionState, StepState


class StateRepository(Protocol):
    """保存并读取状态快照，不包含生命周期迁移规则。"""

    def save_session(self, state: SessionState) -> None:
        """保存会话快照，并校验状态版本。"""

    def get_session(self, session_id: str) -> SessionState | None:
        """按标识读取会话；不存在时返回空值。"""

    def save_run(self, state: RunState) -> None:
        """保存运行快照，并校验状态版本。"""

    def get_run(self, run_id: str) -> RunState | None:
        """按标识读取运行；不存在时返回空值。"""

    def list_runs(self, session_id: str) -> Sequence[RunState]:
        """读取属于指定会话的全部运行。"""

    def save_step(self, state: StepState) -> None:
        """保存步骤快照，并校验状态版本。"""

    def get_step(self, step_id: str) -> StepState | None:
        """按标识读取步骤；不存在时返回空值。"""

    def list_steps(self, run_id: str) -> Sequence[StepState]:
        """读取属于指定运行的全部步骤。"""
