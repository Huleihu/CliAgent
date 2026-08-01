"""Team 领域与文件、线程和 Runtime 适配器之间的稳定端口。"""

from collections.abc import Callable, Sequence
from datetime import datetime
from threading import Event, Thread
from typing import TYPE_CHECKING, Protocol

from .protocol_state import TeamProtocolState
from .schema import (
    InboxReservation,
    Team,
    TeamAssignment,
    TeamMember,
    TeamMessage,
    TeamMessageDraft,
    TeamPromptExecution,
)

if TYPE_CHECKING:
    from .protocol_dispatch import TeamProtocolDispatchResult


class TeamIdGenerator(Protocol):
    """为 Team、成员、分配、消息和预留生成可替换标识。"""

    def new_id(self, *, kind: str) -> str:
        """返回一个尚未被仓储写入的非空标识。"""


class TeamClock(Protocol):
    """为持久时间戳提供可替换的 UTC 时间来源。"""

    def now(self) -> datetime:
        """返回一个带时区的当前时间。"""


class TeamRepository(Protocol):
    """保存 Team 配置快照，不包含成员、消息或执行逻辑。"""

    def add(self, team: Team) -> Team:
        """新增一个 Team。"""

    def get(self, team_id: str) -> Team | None:
        """按标识读取 Team。"""

    def replace(self, team: Team) -> Team:
        """以新的完整 Team 快照替换既有定义。"""


class TeamMemberRepository(Protocol):
    """保存 Team 成员身份及 Session 绑定。"""

    def add(self, member: TeamMember) -> TeamMember:
        """新增成员。"""

    def get(self, member_id: str) -> TeamMember | None:
        """按成员标识读取身份。"""

    def list_for_team(self, team_id: str) -> Sequence[TeamMember]:
        """稳定返回一个 Team 的全部成员。"""

    def replace(self, member: TeamMember) -> TeamMember:
        """以新的完整成员快照替换既有身份。"""


class TeamAssignmentRepository(Protocol):
    """保存 Team 工作分配，不替代 S12 项目任务仓储。"""

    def add(self, assignment: TeamAssignment) -> TeamAssignment:
        """新增一项工作分配。"""

    def get(self, assignment_id: str) -> TeamAssignment | None:
        """按标识读取工作分配。"""

    def list_for_team(self, team_id: str) -> Sequence[TeamAssignment]:
        """稳定返回一个 Team 的全部工作分配。"""

    def list_for_assignee(self, member_id: str) -> Sequence[TeamAssignment]:
        """稳定返回分配给指定成员的工作。"""

    def replace(self, assignment: TeamAssignment) -> TeamAssignment:
        """以新的完整分配快照替换既有记录。"""


class TeamInboxRepository(Protocol):
    """保存接收方有序消息，并提供预留—确认消费协议。"""

    def send(self, draft: TeamMessageDraft) -> TeamMessage:
        """原子分配接收方 sequence 并保存消息；相同幂等键的处理由适配器定义。"""

    def list_unread(
        self,
        *,
        team_id: str,
        recipient_member_id: str,
    ) -> Sequence[TeamMessage]:
        """按 sequence 读取未消费消息，不改变其投递状态。"""

    def reserve_unread(
        self,
        *,
        team_id: str,
        recipient_member_id: str,
        reservation_id: str,
        reserved_at: datetime,
        limit: int,
    ) -> InboxReservation | None:
        """原子预留一批未读消息；没有可用消息时返回空值。"""

    def acknowledge(
        self,
        reservation: InboxReservation,
        *,
        consumer_session_id: str,
        consumer_run_id: str,
        consumed_at: datetime,
    ) -> Sequence[TeamMessage]:
        """确认已经被一个成功 Run 接收的预留消息。"""

    def release(self, reservation: InboxReservation) -> Sequence[TeamMessage]:
        """释放未被成功 Run 确认的预留消息。"""

    def recover_reserved(self, *, team_id: str) -> Sequence[TeamMessage]:
        """将进程中断遗留的预留消息恢复为未读。"""


class TeamProtocolStateRepository(Protocol):
    """保存 S16 协议请求状态，不承担消息投递或响应 dispatch。"""

    def add(self, state: TeamProtocolState) -> TeamProtocolState:
        """新增一项 pending 协议请求。"""

    def get(self, request_id: str) -> TeamProtocolState | None:
        """按 request_id 读取协议状态。"""

    def list_pending_for_team(self, team_id: str) -> Sequence[TeamProtocolState]:
        """稳定返回指定 Team 尚未解决的请求。"""

    def replace(self, state: TeamProtocolState) -> TeamProtocolState:
        """以新的完整协议状态替换既有请求。"""


class TeamProtocolRequestSender(Protocol):
    """持久化协议请求并投递其 request 消息，不负责 Team 成员权限校验或 Runner 唤醒。"""

    def open_request(
        self,
        *,
        state: TeamProtocolState,
        message_id: str,
        idempotency_key: str,
    ) -> tuple[TeamProtocolState, TeamMessage]:
        """保存或幂等重放一个 pending 请求，并将 request 消息投递到目标收件箱。"""


class TeamShutdownRequester(Protocol):
    """受控发起 shutdown 协议的应用服务入口，供父侧工具而非 Runner 调用。"""

    def request_shutdown(
        self,
        *,
        team_id: str,
        lead_member_id: str,
        lead_session_id: str,
        target_member_id: str,
        reason: str,
        request_id: str,
    ) -> tuple[TeamProtocolState, TeamMessage]:
        """校验 Lead 身份后创建 shutdown 请求、投递消息并唤醒目标成员。"""


class TeamProtocolMessageDispatcher(Protocol):
    """将单条收件箱消息解释为协议路由结论，不负责预留、确认或执行 Agent。"""

    def dispatch(self, message: TeamMessage) -> "TeamProtocolDispatchResult":
        """返回消息应转交 Agent、由系统处理、停止成员或作为失败处理的结论。"""


class TeamDispatcher(Protocol):
    """通知进程内 Runner 有成员需要检查工作，不直接执行 Agent。"""

    def signal(self, *, member_id: str) -> None:
        """提示指定成员对应的 worker 尽快检查持久状态。"""


class TeamSignalRegistry(Protocol):
    """供进程内 Runner 注册唤醒 Event 的瞬时端口，不属于 durable Team 状态。"""

    def register(self, *, member_id: str) -> Event:
        """返回指定成员唯一的进程内唤醒事件。"""

    def unregister(self, *, member_id: str, wake_event: Event) -> None:
        """仅移除仍由当前 Runner 持有的唤醒事件。"""


class TeamWaiter(Protocol):
    """隔离 Runner 的 Event 等待，避免单元测试依赖真实 sleep。"""

    def wait(
        self,
        *,
        stop_event: Event,
        wake_event: Event,
        timeout_seconds: float,
    ) -> bool:
        """等待唤醒、超时或停止；返回 True 表示 Runner 应结束。"""


class TeamThreadFactory(Protocol):
    """隔离 daemon 线程创建，允许测试同步接管 Runner 的循环目标。"""

    def start(self, *, target: Callable[[], None], name: str) -> Thread:
        """启动命名线程并返回其句柄。"""


class TeamAgentExecutor(Protocol):
    """将成员输入交给既有 Runtime 创建独立 Run 的适配端口。"""

    def execute(
        self,
        *,
        member: TeamMember,
        prompt: str,
    ) -> TeamPromptExecution:
        """执行一次成员 Run，并返回其 Session、Run 和最终文本。"""


class TeamResultReporter(Protocol):
    """将成员成功 Run 的结果投递给派活者，不负责启动接收方 Run。"""

    def report(
        self,
        *,
        member: TeamMember,
        source_messages: Sequence[TeamMessage],
        execution: TeamPromptExecution,
    ) -> Sequence[TeamMessage]:
        """持久化本次执行对应的结果消息，并返回已投递的消息。"""


class TeamExecutionGate(Protocol):
    """串行化同一 Lead Session 自动 Run 的非阻塞执行租约。"""

    def try_acquire(self) -> bool:
        """执行租约可用时获取它；忙碌时不阻塞。"""

    def release(self) -> None:
        """释放此前成功取得的执行租约。"""
