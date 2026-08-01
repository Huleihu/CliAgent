"""Team 领域与文件、线程和 Runtime 适配器之间的稳定端口。"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from .schema import (
    InboxReservation,
    Team,
    TeamAssignment,
    TeamMember,
    TeamMessage,
    TeamMessageDraft,
    TeamPromptExecution,
)


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


class TeamDispatcher(Protocol):
    """通知进程内 Runner 有成员需要检查工作，不直接执行 Agent。"""

    def signal(self, *, member_id: str) -> None:
        """提示指定成员对应的 worker 尽快检查持久状态。"""


class TeamAgentExecutor(Protocol):
    """将成员输入交给既有 Runtime 创建独立 Run 的适配端口。"""

    def execute(
        self,
        *,
        member: TeamMember,
        prompt: str,
    ) -> TeamPromptExecution:
        """执行一次成员 Run，并返回其 Session、Run 和最终文本。"""
