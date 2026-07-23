"""单次任务运行的不可变生命周期状态。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from .errors import InvalidRunTransitionError
from .timestamps import normalize_utc_timestamp


class RunStatus(StrEnum):
    """运行时处理一次输入或事件时，该次运行可处于的状态。"""

    QUEUED = "queued"
    RECOVERING = "recovering"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    WAITING_EVENT = "waiting_event"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXHAUSTED = "exhausted"


_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({
        RunStatus.RECOVERING,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    }),
    RunStatus.RECOVERING: frozenset({
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_INPUT,
        RunStatus.WAITING_EVENT,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }),
    RunStatus.RUNNING: frozenset({
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_INPUT,
        RunStatus.WAITING_EVENT,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.EXHAUSTED,
    }),
    RunStatus.WAITING_APPROVAL: frozenset({
        RunStatus.RECOVERING,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    }),
    RunStatus.WAITING_INPUT: frozenset({
        RunStatus.RECOVERING,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    }),
    RunStatus.WAITING_EVENT: frozenset({
        RunStatus.RECOVERING,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    }),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.EXHAUSTED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class RunTransition:
    """解释一次已完成状态变更的不可变记录。"""

    source_status: RunStatus
    target_status: RunStatus
    occurred_at: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunState:
    """一次输入处理运行的可恢复生命周期视图。

    状态变更返回新对象，避免调用方静默修改后续仓储或检查点
    需要比较和持久化的状态。
    """

    run_id: str
    session_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    state_version: int = 1
    transition_history: tuple[RunTransition, ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "RunState":
        """创建处于排队状态、使用明确 UTC 时间边界的一次运行。"""

        timestamp = normalize_utc_timestamp(
            created_at or datetime.now(timezone.utc),
            subject="运行",
        )
        return cls(
            run_id=run_id or str(uuid4()),
            session_id=session_id,
            status=RunStatus.QUEUED,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def is_terminal(self) -> bool:
        """判断当前运行是否已进入不可恢复的终态。"""

        return not _ALLOWED_TRANSITIONS[self.status]

    def transition_to(
        self,
        target_status: RunStatus,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> "RunState":
        """返回下一个合法的不可变状态，或拒绝非法跳转。"""

        if target_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidRunTransitionError(
                run_id=self.run_id,
                source_status=self.status,
                target_status=target_status,
            )

        timestamp = normalize_utc_timestamp(
            occurred_at or datetime.now(timezone.utc),
            subject="运行",
        )
        if timestamp < self.updated_at:
            raise ValueError("运行的状态变更时间不能早于当前状态的时间。")

        transition = RunTransition(
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
