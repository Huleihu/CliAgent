from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.cron import CronTask, CronTaskScope, CronTrigger


def _timestamp() -> datetime:
    return datetime(2026, 7, 30, 9, 15, tzinfo=timezone(timedelta(hours=8)))


def _session_task() -> CronTask:
    return CronTask.create(
        task_id="cron-001",
        cron="*/5 * * * *",
        prompt="检查构建状态。",
        owner_session_id="session-001",
        created_at=_timestamp(),
    )


def test_session_only_task_is_immutable_and_normalizes_timestamps() -> None:
    task = _session_task()

    assert task.scope is CronTaskScope.SESSION_ONLY
    assert task.owner_session_id == "session-001"
    assert task.created_at == datetime(2026, 7, 30, 1, 15, tzinfo=timezone.utc)
    with pytest.raises(FrozenInstanceError):
        task.prompt = "不应修改"  # type: ignore[misc]


def test_durable_task_is_workspace_scoped_and_visible_to_every_session() -> None:
    task = CronTask.create(
        task_id="cron-001",
        cron="0 9 * * 1-5",
        prompt="运行每日检查。",
        scope=CronTaskScope.DURABLE,
        created_at=_timestamp(),
    )

    assert task.owner_session_id is None
    assert task.is_visible_to("session-001") is True
    assert task.is_visible_to("session-002") is True


def test_session_only_task_is_visible_only_to_its_owner() -> None:
    task = _session_task()

    assert task.is_visible_to("session-001") is True
    assert task.is_visible_to("session-002") is False


def test_task_marks_an_exact_utc_minute_with_a_new_snapshot() -> None:
    task = _session_task()

    marked = task.mark_enqueued(
        minute=datetime(2026, 7, 30, 9, 15, tzinfo=timezone(timedelta(hours=8)))
    )

    assert task.last_enqueued_minute is None
    assert marked.last_enqueued_minute == datetime(
        2026,
        7,
        30,
        1,
        15,
        tzinfo=timezone.utc,
    )


def test_trigger_binds_a_workspace_task_to_the_current_delivery_session() -> None:
    task = CronTask.create(
        task_id="cron-001",
        cron="0 9 * * *",
        prompt="运行每日检查。",
        scope=CronTaskScope.DURABLE,
        created_at=_timestamp(),
    )

    trigger = CronTrigger.create(
        task=task,
        session_id="session-current",
        scheduled_minute=datetime(2026, 7, 30, 9, 0, tzinfo=timezone(timedelta(hours=8))),
        enqueued_at=_timestamp(),
    )

    assert trigger.task_id == task.task_id
    assert trigger.session_id == "session-current"
    assert trigger.scheduled_minute == datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    assert trigger.enqueued_at == datetime(2026, 7, 30, 1, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: CronTask.create(
                task_id="cron-001",
                cron="* * * * *",
                prompt="任务。",
                scope=CronTaskScope.SESSION_ONLY,
            ),
            "session-only cron 任务必须提供 owner_session_id",
        ),
        (
            lambda: CronTask.create(
                task_id="cron-001",
                cron="* * * * *",
                prompt="任务。",
                scope=CronTaskScope.DURABLE,
                owner_session_id="session-001",
            ),
            "durable cron 任务不能绑定 owner_session_id",
        ),
        (
            lambda: _session_task().mark_enqueued(
                minute=_timestamp().replace(second=1)
            ),
            "minute”必须精确到分钟",
        ),
        (
            lambda: CronTrigger.create(
                task=_session_task(),
                session_id="session-001",
                scheduled_minute=_timestamp().replace(second=1),
            ),
            "scheduled_minute”必须精确到分钟",
        ),
    ],
)
def test_schema_rejects_invalid_scope_and_minute_invariants(
    factory: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()  # type: ignore[operator]
