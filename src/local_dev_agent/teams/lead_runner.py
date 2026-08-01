"""将 Lead 收件箱中的 Team 消息自动交给既有 Runtime 执行。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Event, Thread

from .inbox_prompt import format_inbox_prompt
from .ports import (
    TeamAgentExecutor,
    TeamClock,
    TeamExecutionGate,
    TeamIdGenerator,
    TeamInboxRepository,
    TeamProtocolMessageDispatcher,
    TeamSignalRegistry,
    TeamThreadFactory,
    TeamWaiter,
)
from .protocol_routing import TeamProtocolInboxRouter
from .schema import InboxReservation, TeamMember, TeamMessage, TeamPromptExecution


logger = logging.getLogger(__name__)


class TeamLeadInboxRunner:
    """仅在共享执行租约空闲时消费一个 Lead 收件箱批次并创建独立 Run。"""

    def __init__(
        self,
        *,
        member: TeamMember,
        inbox_repository: TeamInboxRepository,
        agent_executor: TeamAgentExecutor,
        execution_gate: TeamExecutionGate,
        id_generator: TeamIdGenerator,
        clock: TeamClock,
        signal_registry: TeamSignalRegistry,
        waiter: TeamWaiter,
        thread_factory: TeamThreadFactory,
        protocol_dispatcher: TeamProtocolMessageDispatcher | None = None,
        on_execution_completed: Callable[[TeamPromptExecution], None] | None = None,
        batch_size: int = 10,
        check_interval_seconds: float = 1.0,
    ) -> None:
        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        if not all(
            callable(getattr(inbox_repository, method_name, None))
            for method_name in ("reserve_unread", "acknowledge", "release")
        ):
            raise TypeError("inbox_repository 必须提供预留、确认和释放方法。")
        if not callable(getattr(agent_executor, "execute", None)):
            raise TypeError("agent_executor 必须提供 execute 方法。")
        if not all(
            callable(getattr(execution_gate, method_name, None))
            for method_name in ("try_acquire", "release")
        ):
            raise TypeError("execution_gate 必须提供 try_acquire 和 release 方法。")
        if not callable(getattr(id_generator, "new_id", None)):
            raise TypeError("id_generator 必须提供 new_id 方法。")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须提供 now 方法。")
        if not all(
            callable(getattr(signal_registry, method_name, None))
            for method_name in ("register", "unregister")
        ):
            raise TypeError("signal_registry 必须提供注册和注销方法。")
        if not callable(getattr(waiter, "wait", None)):
            raise TypeError("waiter 必须提供 wait 方法。")
        if not callable(getattr(thread_factory, "start", None)):
            raise TypeError("thread_factory 必须提供 start 方法。")
        if protocol_dispatcher is not None and not callable(
            getattr(protocol_dispatcher, "dispatch", None)
        ):
            raise TypeError("protocol_dispatcher 必须提供 dispatch 方法或为 None。")
        if on_execution_completed is not None and not callable(on_execution_completed):
            raise TypeError("on_execution_completed 必须是可调用对象或 None。")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("字段“batch_size”必须是正整数。")
        if (
            isinstance(check_interval_seconds, bool)
            or not isinstance(check_interval_seconds, (int, float))
            or check_interval_seconds <= 0
        ):
            raise ValueError("字段“check_interval_seconds”必须是正数。")
        self._member = member
        self._inbox_repository = inbox_repository
        self._agent_executor = agent_executor
        self._execution_gate = execution_gate
        self._id_generator = id_generator
        self._clock = clock
        self._signal_registry = signal_registry
        self._waiter = waiter
        self._thread_factory = thread_factory
        self._protocol_router = (
            TeamProtocolInboxRouter(dispatcher=protocol_dispatcher)
            if protocol_dispatcher is not None
            else None
        )
        self._on_execution_completed = on_execution_completed
        self._batch_size = batch_size
        self._check_interval_seconds = float(check_interval_seconds)
        self._stop_event = Event()
        self._wake_event: Event | None = None
        self._thread: Thread | None = None

    def start(self) -> Thread:
        """启动唯一的 Lead 收件箱轮询线程，避免并发消费同一收件箱。"""

        if self._thread is not None:
            raise RuntimeError("Team Lead 收件箱 Runner 已启动。")
        self._wake_event = self._signal_registry.register(member_id=self._member.member_id)
        self._thread = self._thread_factory.start(
            target=self._run,
            name=f"team-lead-{self._member.member_id}",
        )
        return self._thread

    def stop(self) -> None:
        """请求停止并唤醒等待线程，不阻塞 CLI 的退出路径。"""

        self._stop_event.set()
        if self._wake_event is not None:
            self._wake_event.set()

    def process_once(self) -> bool:
        """空闲时才预留 Lead 消息；Run 或确认失败时释放本批消息。"""

        if self._protocol_router is not None:
            return self._process_protocol_messages()
        if not self._execution_gate.try_acquire():
            return False
        try:
            reservation = self._reserve_messages()
            if reservation is None:
                return False
            return self._execute_agent_messages(reservation)
        finally:
            self._execution_gate.release()

    def _process_protocol_messages(self) -> bool:
        """协议状态更新无需占用 Lead 执行锁，只有转交 Agent 的消息才申请共享租约。"""

        assert self._protocol_router is not None
        reservation = self._reserve_messages()
        if reservation is None:
            return False
        unprocessed_messages = list(reservation.messages)
        try:
            route = self._protocol_router.route(reservation.messages)
            for message in route.messages_for_system:
                self._acknowledge_protocol_message(reservation, message)
                unprocessed_messages.remove(message)
            for failure in route.failures:
                logger.warning(
                    "Team 协议消息校验失败，已确认消费且不会创建 Lead Run。",
                    extra={
                        "member_id": self._member.member_id,
                        "message_id": failure.message.message_id,
                        "reason": failure.failure_reason,
                    },
                )
            if route.should_stop_member:
                self._release_messages(reservation, unprocessed_messages)
                self.stop()
                return True
            if not route.messages_for_agent:
                return True
            agent_reservation = reservation.subset(route.messages_for_agent)
            if not self._execution_gate.try_acquire():
                self._release_messages(reservation, unprocessed_messages)
                return False
            try:
                return self._execute_agent_messages(agent_reservation)
            finally:
                self._execution_gate.release()
        except Exception:
            self._release_messages(reservation, unprocessed_messages)
            logger.warning(
                "Team 协议消息处理失败，已释放尚未确认的收件箱消息等待后续重投。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return False

    def _reserve_messages(self) -> InboxReservation | None:
        """为当前 Lead 预留一批有序消息，不在这里决定是否需要 Runtime Run。"""

        return self._inbox_repository.reserve_unread(
            team_id=self._member.team_id,
            recipient_member_id=self._member.member_id,
            reservation_id=self._id_generator.new_id(kind="lead-reservation"),
            reserved_at=self._clock.now(),
            limit=self._batch_size,
        )

    def _execute_agent_messages(self, reservation: InboxReservation) -> bool:
        """在调用方已取得 Lead 执行租约时执行一个 Agent 消息子批次。"""

        try:
            execution = self._agent_executor.execute(
                member=self._member,
                prompt=format_inbox_prompt(reservation.messages),
            )
            if execution.session_id != self._member.session_id:
                raise ValueError("Team Lead 执行结果不属于该成员的 Session。")
            self._inbox_repository.acknowledge(
                reservation,
                consumer_session_id=execution.session_id,
                consumer_run_id=execution.run_id,
                consumed_at=self._clock.now(),
            )
            self._notify_execution_completed(execution)
            return True
        except Exception:
            self._release_after_failure(reservation)
            logger.warning(
                "Team Lead 收件箱 Run 失败，已释放收件箱预留消息等待后续重投。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return False

    def _acknowledge_protocol_message(
        self,
        reservation: InboxReservation,
        message: TeamMessage,
    ) -> None:
        """协议消息不启动 Runtime Run，仍用稳定消费标识完整记录其已被系统处理。"""

        self._inbox_repository.acknowledge(
            reservation.subset((message,)),
            consumer_session_id=self._member.session_id,
            consumer_run_id=f"protocol-dispatch-{message.message_id}",
            consumed_at=self._clock.now(),
        )

    def _release_messages(
        self,
        reservation: InboxReservation,
        messages: list[TeamMessage],
    ) -> None:
        """仅释放尚未确认的预留子集，避免将已完成的协议状态更新重新投递。"""

        if messages:
            self._release_after_failure(reservation.subset(tuple(messages)))

    def _notify_execution_completed(self, execution: TeamPromptExecution) -> None:
        """终端展示失败不应导致已确认的 Lead 收件箱消息被重新处理。"""

        if self._on_execution_completed is None:
            return
        try:
            self._on_execution_completed(execution)
        except Exception:
            logger.warning(
                "输出 Team Lead 自动 Run 结果失败，消息已确认消费。",
                exc_info=True,
                extra={"member_id": self._member.member_id, "run_id": execution.run_id},
            )

    def _release_after_failure(self, reservation: InboxReservation) -> None:
        """优先释放本次预留；释放失败不掩盖 Lead Run 的原始异常。"""

        try:
            self._inbox_repository.release(reservation)
        except Exception:
            logger.warning(
                "释放 Team Lead 收件箱预留消息失败，恢复扫描会在后续启动时处理。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )

    def _run(self) -> None:
        """先尝试消费已有消息，再通过 Event 等待新结果或下次检查。"""

        wake_event = self._wake_event
        if wake_event is None:
            raise AssertionError("Team Lead 收件箱 Runner 启动前必须注册唤醒事件。")
        try:
            while not self._stop_event.is_set():
                self.process_once()
                if self._waiter.wait(
                    stop_event=self._stop_event,
                    wake_event=wake_event,
                    timeout_seconds=self._check_interval_seconds,
                ):
                    return
        finally:
            self._signal_registry.unregister(
                member_id=self._member.member_id,
                wake_event=wake_event,
            )
