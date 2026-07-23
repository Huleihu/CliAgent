"""最小内部事件协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from local_dev_agent.domain.state.timestamps import normalize_utc_timestamp


class EventType(StrEnum):
    """当前运行时支持的内部事件类型。"""

    USER_INPUT_RECEIVED = "user.input.received"


@dataclass(frozen=True, slots=True)
class UserInputEvent:
    """表示已经接收、等待 Runtime 处理的一条用户输入。"""

    event_id: str
    session_id: str
    occurred_at: datetime
    content: str
    schema_version: int = 1
    event_type: EventType = field(
        default=EventType.USER_INPUT_RECEIVED,
        init=False,
    )

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        content: str,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> "UserInputEvent":
        """创建带明确会话归属和 UTC 时间边界的用户输入事件。"""

        if not isinstance(session_id, str) or not session_id:
            raise ValueError("用户输入事件必须关联非空会话标识。")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("用户输入事件内容不能为空。")

        timestamp = normalize_utc_timestamp(
            occurred_at or datetime.now(timezone.utc),
            subject="事件",
        )
        return cls(
            event_id=event_id or str(uuid4()),
            session_id=session_id,
            occurred_at=timestamp,
            content=content,
        )
