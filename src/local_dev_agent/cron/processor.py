"""只负责消费 Trigger Queue 的 Queue Processor。"""

import logging

from .ports import CronExecutionGate, CronTriggerConsumer, CronTriggerQueue

logger = logging.getLogger(__name__)


class CronQueueProcessor:
    """仅在执行租约可用时尝试交付队首 Trigger，不检查 cron 时间。"""

    def __init__(self, *, trigger_queue: CronTriggerQueue, gate: CronExecutionGate, consumer: CronTriggerConsumer) -> None:
        if not callable(getattr(trigger_queue, "peek", None)) or not callable(getattr(trigger_queue, "acknowledge", None)):
            raise TypeError("trigger_queue 必须提供 peek 和 acknowledge 方法。")
        if not callable(getattr(gate, "try_acquire", None)) or not callable(getattr(gate, "release", None)):
            raise TypeError("gate 必须提供 try_acquire 和 release 方法。")
        if not callable(getattr(consumer, "consume", None)):
            raise TypeError("consumer 必须提供 consume 方法。")
        self._queue, self._gate, self._consumer = trigger_queue, gate, consumer

    def process_once(self) -> bool:
        """空闲时消费一个 Trigger；已尝试交付的 Trigger 不自动重放。"""

        trigger = self._queue.peek()
        if trigger is None or not self._gate.try_acquire():
            return False
        try:
            trigger = self._queue.peek()
            if trigger is None:
                return False
            try:
                self._consumer.consume(trigger)
            except Exception:
                logger.warning("交付 Cron 触发失败，不自动重放。", exc_info=True)
            self._queue.acknowledge(trigger)
            return True
        finally:
            self._gate.release()
