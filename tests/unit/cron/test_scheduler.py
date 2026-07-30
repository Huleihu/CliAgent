from datetime import datetime, timedelta, timezone

from local_dev_agent.cron import CronScheduler, CronTask, InMemoryCronTriggerQueue


class FakeClock:
    """测试用可推进时钟，不依赖真实墙上时间。"""

    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class MemoryCatalog:
    """保存任意 scope 快照，记录 Scheduler 的替换与删除副作用。"""

    def __init__(self, tasks: tuple[CronTask, ...]) -> None:
        self.tasks = {task.task_id: task for task in tasks}
        self.replaced: list[CronTask] = []
        self.removed: list[str] = []

    def list_visible_to_session(self, session_id: str) -> tuple[CronTask, ...]:
        return tuple(task for task in self.tasks.values() if task.is_visible_to(session_id))

    def replace(self, task: CronTask) -> CronTask:
        self.tasks[task.task_id] = task
        self.replaced.append(task)
        return task

    def remove(self, task_id: str) -> CronTask | None:
        self.removed.append(task_id)
        return self.tasks.pop(task_id, None)


class FailingReplaceCatalog(MemoryCatalog):
    """模拟入队成功后的持久化故障，验证 Scheduler 的进程内防重。"""

    def replace(self, task: CronTask) -> CronTask:
        raise RuntimeError("仓储暂时不可用。")


def _task(
    task_id: str,
    *,
    cron: str = "0 9 * * *",
    recurring: bool = True,
    session_id: str = "session-001",
) -> CronTask:
    return CronTask.create(
        task_id=task_id,
        cron=cron,
        prompt=f"执行 {task_id}。",
        recurring=recurring,
        owner_session_id=session_id,
        created_at=datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
    )


def test_scheduler_enqueues_a_due_recurring_task_only_once_per_utc_minute() -> None:
    clock = FakeClock(datetime(2026, 7, 30, 9, 0, 10, tzinfo=timezone.utc))
    repository = MemoryCatalog((_task("cron-001"),))
    queue = InMemoryCronTriggerQueue()
    scheduler = CronScheduler(
        repository=repository,
        trigger_queue=queue,
        clock=clock,
        session_id="session-001",
    )

    first = scheduler.tick()
    second = scheduler.tick()
    clock.now_value += timedelta(days=1)
    third = scheduler.tick()

    assert [trigger.task_id for trigger in first] == ["cron-001"]
    assert second == ()
    assert [trigger.task_id for trigger in third] == ["cron-001"]
    assert len(repository.replaced) == 2
    assert queue.peek() == first[0]


def test_scheduler_removes_a_one_shot_task_after_successful_enqueue() -> None:
    clock = FakeClock(datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc))
    task = _task("cron-once", recurring=False)
    repository = MemoryCatalog((task,))
    queue = InMemoryCronTriggerQueue()
    scheduler = CronScheduler(
        repository=repository,
        trigger_queue=queue,
        clock=clock,
        session_id="session-001",
    )

    assert [trigger.task_id for trigger in scheduler.tick()] == ["cron-once"]
    assert scheduler.tick() == ()
    assert repository.removed == ["cron-once"]
    assert repository.tasks == {}


def test_scheduler_does_not_enqueue_twice_in_the_same_minute_after_replace_failure() -> None:
    clock = FakeClock(datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc))
    repository = FailingReplaceCatalog((_task("cron-001"),))
    queue = InMemoryCronTriggerQueue()
    scheduler = CronScheduler(
        repository=repository,
        trigger_queue=queue,
        clock=clock,
        session_id="session-001",
    )

    assert scheduler.tick() == ()
    first_trigger = queue.peek()
    assert first_trigger is not None
    assert scheduler.tick() == ()
    assert queue.peek() is first_trigger


def test_scheduler_skips_an_invalid_snapshot_but_keeps_checking_other_jobs() -> None:
    clock = FakeClock(datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc))
    invalid = _task("cron-invalid", cron="? * * * *")
    valid = _task("cron-valid")
    repository = MemoryCatalog((invalid, valid))
    scheduler = CronScheduler(
        repository=repository,
        trigger_queue=InMemoryCronTriggerQueue(),
        clock=clock,
        session_id="session-001",
    )

    assert [trigger.task_id for trigger in scheduler.tick()] == ["cron-valid"]
