from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import CronTask, CronTrigger, InMemoryCronTriggerQueue


def _trigger(task_id: str) -> CronTrigger:
    task = CronTask.create(
        task_id=task_id,
        cron="* * * * *",
        prompt="检查。",
        owner_session_id="session-001",
        created_at=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc),
    )
    return CronTrigger.create(
        task=task,
        session_id="session-001",
        scheduled_minute=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc),
        enqueued_at=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc),
    )


def test_trigger_queue_preserves_fifo_until_the_current_head_is_acknowledged() -> None:
    queue = InMemoryCronTriggerQueue()
    first, second = _trigger("cron-001"), _trigger("cron-002")
    queue.enqueue(first)
    queue.enqueue(second)

    assert queue.peek() is first
    with pytest.raises(ValueError, match="队首"):
        queue.acknowledge(second)
    queue.acknowledge(first)
    assert queue.peek() is second
    queue.acknowledge(second)
    assert queue.peek() is None
