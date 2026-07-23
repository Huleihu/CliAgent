"""单次运行内部步骤的不可变生命周期状态。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from .errors import InvalidStepTransitionError
from .timestamps import normalize_utc_timestamp


class StepType(StrEnum):
    """步骤所代表的运行时动作类型。"""

    PLAN = "plan"
    MODEL = "model"
    TOOL = "tool"
    VERIFY = "verify"
    REFLECT = "reflect"
    DELEGATE = "delegate"


class StepStatus(StrEnum):
    """单个步骤从创建到结束可处于的状态。"""

    PENDING = "pending"
    EXECUTING = "executing"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


_ALLOWED_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset({
        StepStatus.EXECUTING,
        StepStatus.SKIPPED,
    }),
    StepStatus.EXECUTING: frozenset({
        StepStatus.WAITING,
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.UNKNOWN,
    }),
    StepStatus.WAITING: frozenset({
        StepStatus.EXECUTING,
        StepStatus.FAILED,
        StepStatus.SKIPPED,
    }),
    StepStatus.UNKNOWN: frozenset({
        StepStatus.WAITING,
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
    }),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.FAILED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class StepTransition:
    """解释一次已完成步骤状态变更的不可变记录。"""

    source_status: StepStatus
    target_status: StepStatus
    occurred_at: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StepState:
    """一次运行中模型、工具或验证动作的可恢复生命周期视图。

    每次变更返回新对象，并保留状态历史，使后续检查点和追踪记录能够
    判断步骤是否已经执行、正在等待或需要协调不确定结果。
    """

    step_id: str
    run_id: str
    step_type: StepType
    status: StepStatus
    created_at: datetime
    updated_at: datetime
    attempt: int = 1
    state_version: int = 1
    transition_history: tuple[StepTransition, ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        step_type: StepType,
        step_id: str | None = None,
        attempt: int = 1,
        created_at: datetime | None = None,
    ) -> "StepState":
        """创建处于待执行状态、关联到指定运行的一次步骤。"""

        if attempt < 1:
            raise ValueError("步骤尝试次数必须大于或等于 1。")

        timestamp = normalize_utc_timestamp(
            created_at or datetime.now(timezone.utc),
            subject="步骤",
        )
        return cls(
            step_id=step_id or str(uuid4()),
            run_id=run_id,
            step_type=step_type,
            status=StepStatus.PENDING,
            created_at=timestamp,
            updated_at=timestamp,
            attempt=attempt,
        )

    @property
    def is_terminal(self) -> bool:
        """判断当前步骤是否已进入不可恢复的终态。"""

        return not _ALLOWED_TRANSITIONS[self.status]

    def transition_to(
        self,
        target_status: StepStatus,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> "StepState":
        """返回下一个合法的不可变步骤状态，或拒绝非法跳转。"""

        if target_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidStepTransitionError(
                step_id=self.step_id,
                source_status=self.status,
                target_status=target_status,
            )

        timestamp = normalize_utc_timestamp(
            occurred_at or datetime.now(timezone.utc),
            subject="步骤",
        )
        if timestamp < self.updated_at:
            raise ValueError("步骤的状态变更时间不能早于当前状态的时间。")

        transition = StepTransition(
            source_status=self.status,
            target_status=target_status,
            occurred_at=timestamp,
            reason=reason,
        )
        return replace(
            self,
            status=target_status,
            updated_at=timestamp,
            state_version=self.state_version + 1,
            transition_history=(*self.transition_history, transition),
        )
