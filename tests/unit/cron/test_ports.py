from datetime import datetime, timezone

from local_dev_agent.cron import (
    CronClock,
    CronTask,
    CronTaskIdGenerator,
    CronTaskRepository,
    CronTrigger,
    CronTriggerQueue,
)


class FixedCronTaskIdGenerator:
    """用固定标识验证任务标识端口不依赖具体实现。"""

    def new_task_id(self) -> str:
        return "cron-001"


class InMemoryCronTaskRepository:
    """用结构化实现验证定义仓储端口。"""

    def __init__(self) -> None:
        self._tasks: dict[str, CronTask] = {}

    def add(self, task: CronTask) -> CronTask:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> CronTask | None:
        return self._tasks.get(task_id)

    def list_visible_to_session(self, session_id: str) -> tuple[CronTask, ...]:
        return tuple(task for task in self._tasks.values() if task.is_visible_to(session_id))

    def replace(self, task: CronTask) -> CronTask:
        self._tasks[task.task_id] = task
        return task

    def remove(self, task_id: str) -> CronTask | None:
        return self._tasks.pop(task_id, None)


class FixedCronClock:
    """用固定带时区时间验证可替换时钟端口。"""

    def now(self) -> datetime:
        return datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


class InMemoryCronTriggerQueue:
    """用简单队列验证触发传递端口。"""

    def __init__(self) -> None:
        self._triggers: list[CronTrigger] = []

    def enqueue(self, trigger: CronTrigger) -> None:
        self._triggers.append(trigger)

    def peek(self) -> CronTrigger | None:
        return self._triggers[0] if self._triggers else None

    def acknowledge(self, trigger: CronTrigger) -> None:
        if self.peek() is trigger:
            self._triggers.pop(0)


def test_ports_accept_structural_implementations() -> None:
    generator: CronTaskIdGenerator = FixedCronTaskIdGenerator()
    repository: CronTaskRepository = InMemoryCronTaskRepository()
    clock: CronClock = FixedCronClock()
    queue: CronTriggerQueue = InMemoryCronTriggerQueue()
    task = CronTask.create(
        task_id=generator.new_task_id(),
        cron="0 9 * * *",
        prompt="运行检查。",
        owner_session_id="session-001",
        created_at=clock.now(),
    )
    trigger = CronTrigger.create(
        task=task,
        session_id="session-001",
        scheduled_minute=clock.now(),
        enqueued_at=clock.now(),
    )

    assert repository.add(task) is task
    assert repository.get(task.task_id) is task
    assert repository.list_visible_to_session("session-001") == (task,)
    queue.enqueue(trigger)
    assert queue.peek() is trigger
    queue.acknowledge(trigger)
    assert queue.peek() is None
