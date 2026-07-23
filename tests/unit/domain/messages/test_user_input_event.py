from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.domain.messages.events import EventType, UserInputEvent


def test_user_input_event_has_a_stable_protocol_shape() -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)

    event = UserInputEvent.create(
        event_id="event-1",
        session_id="session-1",
        content="继续实现最小运行循环。",
        occurred_at=timestamp,
    )

    assert event.event_id == "event-1"
    assert event.session_id == "session-1"
    assert event.content == "继续实现最小运行循环。"
    assert event.occurred_at == timestamp
    assert event.schema_version == 1
    assert event.event_type is EventType.USER_INPUT_RECEIVED


def test_user_input_event_generates_an_identifier_when_missing() -> None:
    event = UserInputEvent.create(
        session_id="session-1",
        content="开始任务。",
    )

    assert event.event_id


def test_user_input_event_normalizes_an_offset_timestamp_to_utc() -> None:
    offset_timestamp = datetime(
        2026,
        7,
        23,
        17,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )

    event = UserInputEvent.create(
        session_id="session-1",
        content="开始任务。",
        occurred_at=offset_timestamp,
    )

    assert event.occurred_at == datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)


def test_user_input_event_rejects_a_naive_timestamp_with_a_chinese_message() -> None:
    with pytest.raises(ValueError, match="事件时间戳必须包含时区信息"):
        UserInputEvent.create(
            session_id="session-1",
            content="开始任务。",
            occurred_at=datetime(2026, 7, 23, 9, 0),
        )


def test_user_input_event_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="内容不能为空"):
        UserInputEvent.create(session_id="session-1", content="  ")


def test_user_input_event_cannot_be_mutated_directly() -> None:
    event = UserInputEvent.create(session_id="session-1", content="开始任务。")

    with pytest.raises(FrozenInstanceError):
        event.content = "被修改的输入"  # type: ignore[misc]
