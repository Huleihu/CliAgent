from threading import Event

import pytest

from local_dev_agent.cron import CronQueueProcessorRunner, CronSchedulerRunner


class RecordingScheduler:
    """记录运行参数，供运行器测试检查停止事件和等待器传递。"""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, stop_event: Event, waiter: object) -> None:
        self.calls += 1
        waiter.wait(stop_event, 1.0)


class StopOnWait:
    """首次等待即设置停止事件，避免测试出现真实等待。"""

    def wait(self, stop_event: Event, timeout_seconds: float) -> bool:
        stop_event.set()
        return True


class InlineThreadFactory:
    """同步执行线程目标，验证运行器不依赖真实线程调度。"""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start(self, *, target, name: str) -> object:
        self.names.append(name)
        target()
        return object()


class RecordingProcessor:
    """记录队列处理轮次，验证运行器不依赖真实 sleep。"""

    def __init__(self) -> None:
        self.calls = 0

    def process_once(self) -> bool:
        self.calls += 1
        return False


def test_scheduler_runner_uses_injected_waiter_and_thread_factory() -> None:
    scheduler = RecordingScheduler()
    factory = InlineThreadFactory()
    runner = CronSchedulerRunner(
        scheduler=scheduler,  # type: ignore[arg-type]
        waiter=StopOnWait(),
        thread_factory=factory,  # type: ignore[arg-type]
    )

    runner.start()

    assert scheduler.calls == 1
    assert factory.names == ["cron-scheduler"]
    with pytest.raises(RuntimeError, match="已启动"):
        runner.start()


def test_queue_processor_runner_uses_injected_waiter_and_thread_factory() -> None:
    processor = RecordingProcessor()
    factory = InlineThreadFactory()
    runner = CronQueueProcessorRunner(
        processor=processor,  # type: ignore[arg-type]
        waiter=StopOnWait(),
        thread_factory=factory,  # type: ignore[arg-type]
    )

    runner.start()

    assert processor.calls == 1
    assert factory.names == ["cron-queue-processor"]
    with pytest.raises(RuntimeError, match="已启动"):
        runner.start()
