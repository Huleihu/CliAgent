"""将持久 Team 收件箱安全交给既有 Runtime 执行端口的成员 Runner。"""

from __future__ import annotations

import logging
from threading import Event, Thread

from .autonomous_work_prompt import format_autonomous_work_prompt
from .inbox_prompt import format_inbox_prompt
from .ports import (
    TeamAgentExecutor,
    TeamAutonomousResultReporter,
    TeamAutonomousWorkSource,
    TeamAutonomousWorkVerifier,
    TeamClock,
    TeamIdGenerator,
    TeamInboxRepository,
    TeamProtocolMessageDispatcher,
    TeamResultReporter,
    TeamSignalRegistry,
    TeamThreadFactory,
    TeamWaiter,
)
from .protocol_routing import TeamProtocolInboxRouter
from .schema import (
    InboxReservation,
    TeamAutonomousWorkItem,
    TeamMember,
    TeamMessage,
    TeamPromptExecution,
)
from local_dev_agent.worktrees import WorktreeRunDirectoryResolver


logger = logging.getLogger(__name__)


class TeamMemberRunner:
    """为一个持久成员串行消费收件箱，不直接进入 Runtime 或更改其他领域状态。"""

    def __init__(
        self,
        *,
        member: TeamMember,
        inbox_repository: TeamInboxRepository,
        agent_executor: TeamAgentExecutor,
        result_reporter: TeamResultReporter,
        id_generator: TeamIdGenerator,
        clock: TeamClock,
        signal_registry: TeamSignalRegistry,
        waiter: TeamWaiter,
        thread_factory: TeamThreadFactory,
        protocol_dispatcher: TeamProtocolMessageDispatcher | None = None,
        autonomous_work_source: TeamAutonomousWorkSource | None = None,
        autonomous_work_verifier: TeamAutonomousWorkVerifier | None = None,
        autonomous_result_reporter: TeamAutonomousResultReporter | None = None,
        autonomous_worktree_directory_resolver: WorktreeRunDirectoryResolver | None = None,
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
        if not callable(getattr(result_reporter, "report", None)):
            raise TypeError("result_reporter 必须提供 report 方法。")
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
        if autonomous_work_source is not None and not callable(
            getattr(autonomous_work_source, "claim_next_work", None)
        ):
            raise TypeError("autonomous_work_source 必须提供 claim_next_work 方法或为 None。")
        if autonomous_work_verifier is not None and not callable(
            getattr(autonomous_work_verifier, "verify", None)
        ):
            raise TypeError("autonomous_work_verifier 必须提供 verify 方法或为 None。")
        if autonomous_result_reporter is not None and not callable(
            getattr(autonomous_result_reporter, "report", None)
        ):
            raise TypeError("autonomous_result_reporter 必须提供 report 方法或为 None。")
        if autonomous_worktree_directory_resolver is not None and not callable(
            getattr(autonomous_worktree_directory_resolver, "resolve", None)
        ):
            raise TypeError("autonomous_worktree_directory_resolver 必须提供 resolve 方法或为 None。")
        if (autonomous_work_verifier is None) != (autonomous_result_reporter is None):
            raise ValueError("自主任务核验器和结果回传器必须同时配置或同时省略。")
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
        self._result_reporter = result_reporter
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
        self._autonomous_work_source = autonomous_work_source
        self._autonomous_work_verifier = autonomous_work_verifier
        self._autonomous_result_reporter = autonomous_result_reporter
        self._autonomous_worktree_directory_resolver = autonomous_worktree_directory_resolver
        self._batch_size = batch_size
        self._check_interval_seconds = float(check_interval_seconds)
        self._stop_event = Event()
        self._wake_event: Event | None = None
        self._thread: Thread | None = None

    def start(self) -> Thread:
        """启动一个成员 Runner；重复启动会拒绝以避免并发消费同一收件箱。"""

        if self._thread is not None:
            raise RuntimeError("Team 成员 Runner 已启动。")
        self._wake_event = self._signal_registry.register(member_id=self._member.member_id)
        self._thread = self._thread_factory.start(
            target=self._run,
            name=f"team-member-{self._member.member_id}",
        )
        return self._thread

    def stop(self) -> None:
        """请求停止并唤醒等待中的线程；不 join，CLI 可立即退出。"""

        self._stop_event.set()
        if self._wake_event is not None:
            self._wake_event.set()

    def process_once(self) -> bool:
        """优先消费收件箱；只有收件箱为空时才尝试领取并执行自主任务。"""

        reservation = self._inbox_repository.reserve_unread(
            team_id=self._member.team_id,
            recipient_member_id=self._member.member_id,
            reservation_id=self._id_generator.new_id(kind="reservation"),
            reserved_at=self._clock.now(),
            limit=self._batch_size,
        )
        if reservation is None:
            return self._execute_autonomous_work()
        if self._protocol_router is None:
            return self._execute_agent_messages(reservation)
        return self._process_protocol_messages(reservation)

    def _execute_autonomous_work(self) -> bool:
        """在没有收件箱工作时执行一项已认领任务，并交由可选核验器确认结果。"""

        if self._autonomous_work_source is None:
            return False
        try:
            work_item = self._autonomous_work_source.claim_next_work(member=self._member)
        except Exception:
            logger.warning(
                "获取 Team 自主任务失败，成员将在后续轮询时重试。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return False
        if work_item is None:
            return False
        try:
            execution = self._execute_autonomous_work_item(work_item)
            if execution.session_id != self._member.session_id:
                raise ValueError("Team 自主任务执行结果不属于该成员的 Session。")
            return self._verify_and_report_autonomous_work(
                work_item=work_item,
                execution=execution,
            )
        except Exception:
            logger.warning(
                "Team 自主任务 Run 失败，任务状态保持不变并等待后续处理。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return self._verify_and_report_autonomous_work(
                work_item=work_item,
                execution=None,
            )

    def _execute_autonomous_work_item(
        self,
        work_item: TeamAutonomousWorkItem,
    ) -> TeamPromptExecution:
        """仅在配置了 S18 目录解析器时把任务工作树传入成员 Run。"""

        prompt = format_autonomous_work_prompt(work_item)
        if self._autonomous_worktree_directory_resolver is None:
            return self._agent_executor.execute(member=self._member, prompt=prompt)
        working_directory = self._autonomous_worktree_directory_resolver.resolve(
            worktree_name=work_item.worktree
        )
        return self._agent_executor.execute(
            member=self._member,
            prompt=prompt,
            working_directory=working_directory,
        )

    def _verify_and_report_autonomous_work(
        self,
        *,
        work_item: TeamAutonomousWorkItem,
        execution: TeamPromptExecution | None,
    ) -> bool:
        """可选地核验并回传自主工作；未装配时保持第三步的执行兼容行为。"""

        if self._autonomous_work_verifier is None:
            return execution is not None
        assert self._autonomous_result_reporter is not None
        try:
            outcome = self._autonomous_work_verifier.verify(
                member=self._member,
                work_item=work_item,
                execution=execution,
            )
            self._autonomous_result_reporter.report(
                member=self._member,
                outcome=outcome,
            )
            return outcome.completed
        except Exception:
            logger.warning(
                "Team 自主任务结果核验或回传失败，任务状态保持不变并等待后续处理。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return False

    def _process_protocol_messages(self, reservation: InboxReservation) -> bool:
        """先消费无需模型参与的协议消息，再把剩余有效消息作为一个子批次交给 Agent。"""

        assert self._protocol_router is not None
        unprocessed_messages = list(reservation.messages)
        try:
            route = self._protocol_router.route(reservation.messages)
            for message in route.messages_for_system:
                self._acknowledge_protocol_message(reservation, message)
                unprocessed_messages.remove(message)
            for failure in route.failures:
                logger.warning(
                    "Team 协议消息校验失败，已确认消费且不会创建 Agent Run。",
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
            return self._execute_agent_messages(
                agent_reservation,
                release_reservation=reservation.subset(tuple(unprocessed_messages)),
            )
        except Exception:
            self._release_messages(reservation, unprocessed_messages)
            logger.warning(
                "Team 协议消息处理失败，已释放尚未确认的收件箱消息等待后续重投。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return False

    def _execute_agent_messages(
        self,
        reservation: InboxReservation,
        *,
        release_reservation: InboxReservation | None = None,
    ) -> bool:
        """执行一个已筛选的 Agent 消息子批次；失败只释放尚未确认的消息。"""

        pending_reservation = release_reservation or reservation
        try:
            execution = self._agent_executor.execute(
                member=self._member,
                prompt=format_inbox_prompt(reservation.messages),
            )
            if execution.session_id != self._member.session_id:
                raise ValueError("Team Agent 执行结果不属于该成员的 Session。")
            self._result_reporter.report(
                member=self._member,
                source_messages=reservation.messages,
                execution=execution,
            )
            self._inbox_repository.acknowledge(
                reservation,
                consumer_session_id=execution.session_id,
                consumer_run_id=execution.run_id,
                consumed_at=self._clock.now(),
            )
            return True
        except Exception:
            self._release_after_failure(pending_reservation)
            logger.warning(
                "Team 成员 Run 失败，已释放收件箱预留消息等待后续重投。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )
            return False

    def _acknowledge_protocol_message(
        self,
        reservation: InboxReservation,
        message: TeamMessage,
    ) -> None:
        """协议处理未创建 Runtime Run，使用稳定消费标识记录已完成的系统动作。"""

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
        """仅释放尚未确认的预留子集，避免覆盖已经完成的协议消费。"""

        if messages:
            self._release_after_failure(reservation.subset(tuple(messages)))

    def _release_after_failure(self, reservation: InboxReservation) -> None:
        """优先释放本次预留；释放错误不掩盖原始执行失败的日志上下文。"""

        try:
            self._inbox_repository.release(reservation)
        except Exception:
            logger.warning(
                "释放 Team 收件箱预留消息失败，恢复扫描会在后续启动时处理。",
                exc_info=True,
                extra={"member_id": self._member.member_id},
            )

    def _run(self) -> None:
        """先检查已有持久消息，再经可替换等待器等待唤醒或下一次检查。"""

        wake_event = self._wake_event
        if wake_event is None:
            raise AssertionError("Team 成员 Runner 启动前必须注册唤醒事件。")
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
