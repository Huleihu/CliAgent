"""Cron 调度定义与触发事实的不可变领域快照。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum


def _require_nonempty_text(field_name: str, value: str) -> str:
    """拒绝无法安全标识、展示或交付的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


def _normalize_utc_timestamp(value: datetime, *, field_name: str) -> datetime:
    """统一使用带时区 UTC 时间，避免跨适配器比较产生歧义。"""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"字段“{field_name}”必须是带时区的 datetime。")
    return value.astimezone(timezone.utc)


def _normalize_utc_minute(value: datetime, *, field_name: str) -> datetime:
    """收束到精确分钟，作为同一分钟防重的稳定标记。"""

    timestamp = _normalize_utc_timestamp(value, field_name=field_name)
    if timestamp.second != 0 or timestamp.microsecond != 0:
        raise ValueError(f"字段“{field_name}”必须精确到分钟。")
    return timestamp


class CronTaskScope(StrEnum):
    """区分工作区 durable 定义和当前 Session 的内存定义。"""

    DURABLE = "durable"
    SESSION_ONLY = "session_only"


@dataclass(frozen=True, slots=True)
class CronTask:
    """一个尚未执行的 cron 调度定义及其最近一次成功入队分钟。"""

    task_id: str
    cron: str
    prompt: str
    recurring: bool
    scope: CronTaskScope
    created_at: datetime
    owner_session_id: str | None = None
    last_enqueued_minute: datetime | None = None

    def __post_init__(self) -> None:
        """校验作用域、Session 归属和防重状态的一致性。"""

        object.__setattr__(self, "task_id", _require_nonempty_text("task_id", self.task_id))
        object.__setattr__(self, "cron", _require_nonempty_text("cron", self.cron))
        object.__setattr__(self, "prompt", _require_nonempty_text("prompt", self.prompt))
        if not isinstance(self.recurring, bool):
            raise ValueError("字段“recurring”必须是布尔值。")
        if not isinstance(self.scope, CronTaskScope):
            raise ValueError("字段“scope”必须是 CronTaskScope。")
        object.__setattr__(
            self,
            "created_at",
            _normalize_utc_timestamp(self.created_at, field_name="created_at"),
        )
        self._validate_owner_session_id()
        if self.last_enqueued_minute is not None:
            object.__setattr__(
                self,
                "last_enqueued_minute",
                _normalize_utc_minute(
                    self.last_enqueued_minute,
                    field_name="last_enqueued_minute",
                ),
            )

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        cron: str,
        prompt: str,
        recurring: bool = True,
        scope: CronTaskScope = CronTaskScope.SESSION_ONLY,
        owner_session_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "CronTask":
        """创建新定义；session-only 任务必须显式归属一个 Session。"""

        return cls(
            task_id=task_id,
            cron=cron,
            prompt=prompt,
            recurring=recurring,
            scope=scope,
            created_at=created_at or datetime.now(timezone.utc),
            owner_session_id=owner_session_id,
        )

    def is_visible_to(self, session_id: str) -> bool:
        """判断当前 Session 是否可以读取并调度此定义。"""

        normalized_session_id = _require_nonempty_text("session_id", session_id)
        return self.scope is CronTaskScope.DURABLE or (
            self.owner_session_id == normalized_session_id
        )

    def mark_enqueued(self, *, minute: datetime) -> "CronTask":
        """返回记录成功入队分钟的新快照，不直接修改既有定义。"""

        return replace(
            self,
            last_enqueued_minute=_normalize_utc_minute(minute, field_name="minute"),
        )

    def _validate_owner_session_id(self) -> None:
        """durable 定义归属工作区，session-only 定义归属创建它的 Session。"""

        if self.scope is CronTaskScope.DURABLE:
            if self.owner_session_id is not None:
                raise ValueError("durable cron 任务不能绑定 owner_session_id。")
            return
        if self.owner_session_id is None:
            raise ValueError("session-only cron 任务必须提供 owner_session_id。")
        object.__setattr__(
            self,
            "owner_session_id",
            _require_nonempty_text("owner_session_id", self.owner_session_id),
        )


@dataclass(frozen=True, slots=True)
class CronTrigger:
    """一次已经到期、等待交付给指定 Session 的独立触发事实。"""

    task_id: str
    session_id: str
    prompt: str
    scheduled_minute: datetime
    enqueued_at: datetime

    def __post_init__(self) -> None:
        """冻结任务身份、目标 Session 和两类时间语义。"""

        object.__setattr__(self, "task_id", _require_nonempty_text("task_id", self.task_id))
        object.__setattr__(self, "session_id", _require_nonempty_text("session_id", self.session_id))
        object.__setattr__(self, "prompt", _require_nonempty_text("prompt", self.prompt))
        object.__setattr__(
            self,
            "scheduled_minute",
            _normalize_utc_minute(self.scheduled_minute, field_name="scheduled_minute"),
        )
        object.__setattr__(
            self,
            "enqueued_at",
            _normalize_utc_timestamp(self.enqueued_at, field_name="enqueued_at"),
        )

    @classmethod
    def create(
        cls,
        *,
        task: CronTask,
        session_id: str,
        scheduled_minute: datetime,
        enqueued_at: datetime | None = None,
    ) -> "CronTrigger":
        """从已验证定义派生一次绑定交付 Session 的触发快照。"""

        if not isinstance(task, CronTask):
            raise TypeError("task 必须是 CronTask 对象。")
        return cls(
            task_id=task.task_id,
            session_id=session_id,
            prompt=task.prompt,
            scheduled_minute=scheduled_minute,
            enqueued_at=enqueued_at or datetime.now(timezone.utc),
        )
