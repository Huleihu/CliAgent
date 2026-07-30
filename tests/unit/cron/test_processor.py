from datetime import datetime, timezone

from local_dev_agent.cron import CronQueueProcessor, CronTask, CronTrigger, InMemoryCronTriggerQueue


class Gate:
    def __init__(self, available: bool = True) -> None:
        self.available, self.released = available, 0
    def try_acquire(self) -> bool:
        return self.available
    def release(self) -> None:
        self.released += 1


class Consumer:
    def __init__(self) -> None:
        self.tasks: list[str] = []
    def consume(self, trigger: CronTrigger) -> None:
        self.tasks.append(trigger.task_id)


class FailingConsumer:
    def consume(self, trigger: CronTrigger) -> None:
        raise RuntimeError("交付失败。")


def test_processor_leaves_queue_when_busy_and_acknowledges_after_delivery() -> None:
    task = CronTask.create(task_id="cron-001", cron="* * * * *", prompt="检查。", owner_session_id="session-001", created_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc))
    trigger = CronTrigger.create(task=task, session_id="session-001", scheduled_minute=datetime(2026, 7, 30, 9, tzinfo=timezone.utc), enqueued_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc))
    queue, consumer = InMemoryCronTriggerQueue(), Consumer()
    queue.enqueue(trigger)
    assert CronQueueProcessor(trigger_queue=queue, gate=Gate(False), consumer=consumer).process_once() is False
    assert queue.peek() is trigger
    gate = Gate()
    assert CronQueueProcessor(trigger_queue=queue, gate=gate, consumer=consumer).process_once() is True
    assert consumer.tasks == ["cron-001"] and queue.peek() is None and gate.released == 1


def test_processor_acknowledges_trigger_after_consumer_failure() -> None:
    task = CronTask.create(task_id="cron-001", cron="* * * * *", prompt="检查。", owner_session_id="session-001", created_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc))
    trigger = CronTrigger.create(task=task, session_id="session-001", scheduled_minute=datetime(2026, 7, 30, 9, tzinfo=timezone.utc), enqueued_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc))
    queue, gate = InMemoryCronTriggerQueue(), Gate()
    queue.enqueue(trigger)

    assert CronQueueProcessor(trigger_queue=queue, gate=gate, consumer=FailingConsumer()).process_once() is True
    assert queue.peek() is None and gate.released == 1
