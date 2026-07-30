from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import CronTask, CronTrigger, SessionBoundCronTriggerConsumer


def _trigger(*, session_id: str = "session-001") -> CronTrigger:
    task = CronTask.create(
        task_id="cron-001",
        cron="0 9 * * *",
        prompt="运行检查。",
        owner_session_id=session_id,
        created_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc),
    )
    return CronTrigger.create(
        task=task,
        session_id=session_id,
        scheduled_minute=datetime(2026, 7, 30, 9, tzinfo=timezone.utc),
        enqueued_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc),
    )


def test_session_bound_consumer_forwards_only_its_own_trigger_prompt() -> None:
    prompts: list[str] = []
    consumer = SessionBoundCronTriggerConsumer(
        session_id="session-001",
        run_prompt=prompts.append,
    )

    consumer.consume(_trigger())

    assert prompts == ["运行检查。"]


def test_session_bound_consumer_rejects_other_session_trigger() -> None:
    consumer = SessionBoundCronTriggerConsumer(
        session_id="session-001",
        run_prompt=lambda _: None,
    )

    with pytest.raises(ValueError, match="不属于当前 Session"):
        consumer.consume(_trigger(session_id="session-002"))
