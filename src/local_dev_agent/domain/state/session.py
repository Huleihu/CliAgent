"""跨多个运行的不可变会话生命周期状态。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from .errors import InvalidSessionTransitionError
from .timestamps import normalize_utc_timestamp


class SessionStatus(StrEnum):
    """会话从创建到归档或人工处理可处于的状态。"""

    CREATED = "created"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"
    CORRUPTED = "corrupted"
    NEEDS_MIGRATION = "needs_migration"


_ALLOWED_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.CREATED: frozenset({SessionStatus.ACTIVE}),
    SessionStatus.ACTIVE: frozenset({
        SessionStatus.SUSPENDED,
        SessionStatus.ARCHIVED,
    }),
    SessionStatus.SUSPENDED: frozenset({
        SessionStatus.ACTIVE,
        SessionStatus.ARCHIVED,
        SessionStatus.CORRUPTED,
        SessionStatus.NEEDS_MIGRATION,
    }),
    SessionStatus.ARCHIVED: frozenset(),
    SessionStatus.CORRUPTED: frozenset(),
    SessionStatus.NEEDS_MIGRATION: frozenset(),
}


@dataclass(frozen=True, slots=True)
class SessionTransition:
    """解释一次已完成会话生命周期变更的不可变记录。"""

    source_status: SessionStatus
    target_status: SessionStatus
    occurred_at: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SessionState:
    """跨多个运行的会话身份、生命周期和当前运行关联视图。

    会话仅保留当前活跃运行的标识；完整运行历史由后续仓储通过
    ``RunState.session_id`` 查询，避免在会话快照中重复保存运行状态。
    """

    session_id: str
    tenant_id: str
    user_id: str
    project_id: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    last_active_at: datetime
    active_run_id: str | None = None
    state_version: int = 1
    transition_history: tuple[SessionTransition, ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        user_id: str,
        project_id: str,
        session_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "SessionState":
        """创建处于已创建状态、使用明确 UTC 时间边界的会话。"""

        timestamp = normalize_utc_timestamp(
            created_at or datetime.now(timezone.utc),
            subject="会话",
        )
        return cls(
            session_id=session_id or str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            status=SessionStatus.CREATED,
            created_at=timestamp,
            updated_at=timestamp,
            last_active_at=timestamp,
        )

    @property
    def is_terminal(self) -> bool:
        """判断当前会话是否只能由后续人工修复或迁移处理。"""

        return not _ALLOWED_TRANSITIONS[self.status]

    def start_run(
        self,
        run_id: str,
        *,
        occurred_at: datetime | None = None,
    ) -> "SessionState":
        """关联新的当前运行，并在首次运行时激活会话。"""

        if self.status not in {SessionStatus.CREATED, SessionStatus.ACTIVE}:
            raise ValueError("只有已创建或活跃的会话可以启动运行。")
        if self.active_run_id is not None:
            raise ValueError("会话已有活跃运行，必须先结束后才能启动新的运行。")

        timestamp = self._normalize_change_timestamp(occurred_at)
        if self.status is SessionStatus.CREATED:
            transition = SessionTransition(
                source_status=self.status,
                target_status=SessionStatus.ACTIVE,
                occurred_at=timestamp,
                reason="启动首个运行。",
            )
            return replace(
                self,
                status=SessionStatus.ACTIVE,
                active_run_id=run_id,
                updated_at=timestamp,
                last_active_at=timestamp,
                state_version=self.state_version + 1,
                transition_history=(*self.transition_history, transition),
            )

        return replace(
            self,
            active_run_id=run_id,
            updated_at=timestamp,
            last_active_at=timestamp,
            state_version=self.state_version + 1,
        )

    def finish_run(
        self,
        run_id: str,
        *,
        occurred_at: datetime | None = None,
    ) -> "SessionState":
        """结束当前匹配的运行，使会话可顺序关联下一次运行。"""

        if self.active_run_id is None:
            raise ValueError("会话当前没有可结束的活跃运行。")
        if self.active_run_id != run_id:
            raise ValueError("只能结束会话当前关联的活跃运行。")

        timestamp = self._normalize_change_timestamp(occurred_at)
        return replace(
            self,
            active_run_id=None,
            updated_at=timestamp,
            last_active_at=timestamp,
            state_version=self.state_version + 1,
        )

    def transition_to(
        self,
        target_status: SessionStatus,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> "SessionState":
        """返回下一个合法的不可变会话状态，或拒绝非法跳转。"""

        if target_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidSessionTransitionError(
                session_id=self.session_id,
                source_status=self.status,
                target_status=target_status,
            )
        if self.active_run_id is not None:
            raise ValueError("会话存在活跃运行时不能改变会话生命周期状态。")

        timestamp = self._normalize_change_timestamp(occurred_at)
        transition = SessionTransition(
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

    def _normalize_change_timestamp(self, occurred_at: datetime | None) -> datetime:
        """统一校验状态变更时间，防止快照时间线倒退。"""

        timestamp = normalize_utc_timestamp(
            occurred_at or datetime.now(timezone.utc),
            subject="会话",
        )
        if timestamp < self.updated_at:
            raise ValueError("会话的状态变更时间不能早于当前状态的时间。")
        return timestamp
