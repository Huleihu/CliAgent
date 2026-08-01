"""协调 Team 持久快照与通知端口的应用服务。"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import TeamEntityNotFoundError, TeamProtocolNotConfiguredError
from .ports import (
    TeamAssignmentRepository,
    TeamClock,
    TeamDispatcher,
    TeamIdGenerator,
    TeamInboxRepository,
    TeamMemberRepository,
    TeamProtocolRequestSender,
    TeamRepository,
)
from .protocol_state import TeamProtocolState
from .protocol_types import TeamMessageType, TeamProtocolType
from .schema import (
    Team,
    TeamAssignment,
    TeamAssignmentStatus,
    TeamMember,
    TeamMemberStatus,
    TeamMessage,
    TeamMessageDraft,
    TeamStatus,
)


@dataclass(frozen=True, slots=True)
class TeamRecoveryResult:
    """一次显式恢复扫描的结果，不代表应用关闭期间发生过执行。"""

    released_messages: tuple[TeamMessage, ...]
    recovery_pending_assignments: tuple[TeamAssignment, ...]


class TeamService:
    """只编排 Team 领域端口，不创建线程、不直接调用 Runtime 或跨包访问状态。"""

    def __init__(
        self,
        *,
        team_repository: TeamRepository,
        member_repository: TeamMemberRepository,
        assignment_repository: TeamAssignmentRepository,
        inbox_repository: TeamInboxRepository,
        id_generator: TeamIdGenerator,
        clock: TeamClock,
        dispatcher: TeamDispatcher,
        protocol_request_sender: TeamProtocolRequestSender | None = None,
    ) -> None:
        self._team_repository = team_repository
        self._member_repository = member_repository
        self._assignment_repository = assignment_repository
        self._inbox_repository = inbox_repository
        self._id_generator = id_generator
        self._clock = clock
        self._dispatcher = dispatcher
        if protocol_request_sender is not None and not callable(
            getattr(protocol_request_sender, "open_request", None)
        ):
            raise TypeError("protocol_request_sender 必须提供 open_request 方法或为 None。")
        self._protocol_request_sender = protocol_request_sender

    def create_team(
        self,
        *,
        workspace_id: str,
        lead_name: str,
        lead_role: str,
        lead_session_id: str,
    ) -> tuple[Team, TeamMember]:
        """创建 Team 与 Lead 身份；两份独立快照均按各自文件原子写入。"""

        timestamp = self._clock.now()
        lead_member = TeamMember.create(
            member_id=self._id_generator.new_id(kind="member"),
            team_id=self._id_generator.new_id(kind="team"),
            name=lead_name,
            role=lead_role,
            session_id=lead_session_id,
            created_at=timestamp,
        )
        team = Team.create(
            team_id=lead_member.team_id,
            workspace_id=workspace_id,
            lead_member_id=lead_member.member_id,
            created_at=timestamp,
        )
        self._team_repository.add(team)
        self._member_repository.add(lead_member)
        return team, lead_member

    def add_teammate(
        self,
        *,
        team_id: str,
        lead_member_id: str,
        lead_session_id: str,
        name: str,
        role: str,
        session_id: str,
    ) -> TeamMember:
        """将持久成员身份加入活动 Team，不启动成员的 Agent Run。"""

        team = self._require_active_team(team_id)
        if team.lead_member_id != lead_member_id:
            raise ValueError("只有 Team Lead 可以添加成员。")
        self._require_active_member_for_session(
            team_id=team_id,
            member_id=lead_member_id,
            session_id=lead_session_id,
        )
        member = TeamMember.create(
            member_id=self._id_generator.new_id(kind="member"),
            team_id=team_id,
            name=name,
            role=role,
            session_id=session_id,
            created_at=self._clock.now(),
        )
        return self._member_repository.add(member)

    def assign_work(
        self,
        *,
        team_id: str,
        assigned_by_member_id: str,
        assigned_by_session_id: str,
        assignee_member_id: str,
        prompt: str,
        project_task_id: str | None = None,
        assignment_id: str | None = None,
    ) -> TeamAssignment:
        """保存独立工作分配，再投递可唤醒成员的 assignment 消息。"""

        team = self._require_active_team(team_id)
        if team.lead_member_id != assigned_by_member_id:
            raise ValueError("只有 Team Lead 可以分配工作。")
        self._require_active_member_for_session(
            team_id=team_id,
            member_id=assigned_by_member_id,
            session_id=assigned_by_session_id,
        )
        self._require_active_member(team_id, assignee_member_id)
        if assigned_by_member_id == assignee_member_id:
            raise ValueError("工作分配方和接收方不能是同一成员。")
        stable_assignment_id = assignment_id or self._id_generator.new_id(kind="assignment")
        existing = self._assignment_repository.get(stable_assignment_id)
        if existing is not None:
            self._require_same_assignment_request(
                existing,
                team_id=team_id,
                assigned_by_member_id=assigned_by_member_id,
                assignee_member_id=assignee_member_id,
                prompt=prompt,
                project_task_id=project_task_id,
            )
            self._send_assignment_message(existing)
            self._dispatcher.signal(member_id=assignee_member_id)
            return existing
        assignment = TeamAssignment.create(
            assignment_id=stable_assignment_id,
            team_id=team_id,
            assigned_by_member_id=assigned_by_member_id,
            assignee_member_id=assignee_member_id,
            prompt=prompt,
            project_task_id=project_task_id,
            created_at=self._clock.now(),
        )
        self._assignment_repository.add(assignment)
        self._send_assignment_message(assignment)
        self._dispatcher.signal(member_id=assignee_member_id)
        return assignment

    def send_message(
        self,
        *,
        team_id: str,
        sender_member_id: str,
        sender_session_id: str,
        recipient_member_id: str,
        content: str,
        idempotency_key: str,
        message_type: TeamMessageType = TeamMessageType.PLAIN,
        message_id: str | None = None,
    ) -> TeamMessage:
        """投递一条成员间消息，并仅用 Dispatcher 唤醒进程内 Runner。"""

        self._require_active_member_for_session(
            team_id=team_id,
            member_id=sender_member_id,
            session_id=sender_session_id,
        )
        self._require_active_member(team_id, recipient_member_id)
        if sender_member_id == recipient_member_id:
            raise ValueError("消息发送方和接收方不能是同一成员。")
        message = self._inbox_repository.send(
            TeamMessageDraft.create(
                message_id=message_id or self._id_generator.new_id(kind="message"),
                team_id=team_id,
                sender_member_id=sender_member_id,
                recipient_member_id=recipient_member_id,
                message_type=message_type,
                content=content,
                idempotency_key=idempotency_key,
                created_at=self._clock.now(),
            )
        )
        self._dispatcher.signal(member_id=recipient_member_id)
        return message

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
        """由当前 Lead 发起可追踪的关闭握手，成员收到后才会决定停止自身 Runner。"""

        team = self._require_active_team(team_id)
        if team.lead_member_id != lead_member_id:
            raise ValueError("只有 Team Lead 可以发起成员关闭请求。")
        self._require_active_member_for_session(
            team_id=team_id,
            member_id=lead_member_id,
            session_id=lead_session_id,
        )
        target_member = self._require_active_member(team_id, target_member_id)
        if target_member.member_id == lead_member_id:
            raise ValueError("不能通过成员关闭协议停止 Team Lead。")
        if self._protocol_request_sender is None:
            raise TeamProtocolNotConfiguredError()
        state = TeamProtocolState.create(
            request_id=request_id,
            team_id=team_id,
            protocol_type=TeamProtocolType.SHUTDOWN,
            sender_member_id=lead_member_id,
            target_member_id=target_member.member_id,
            payload=reason,
            created_at=self._clock.now(),
        )
        persisted_state, message = self._protocol_request_sender.open_request(
            state=state,
            message_id=f"shutdown-request-{request_id}",
            idempotency_key=f"shutdown:{request_id}",
        )
        self._dispatcher.signal(member_id=target_member.member_id)
        return persisted_state, message

    def recover_team(self, *, team_id: str) -> TeamRecoveryResult:
        """显式释放遗留预留并标记中断分配；不自动新建或执行任何 Run。"""

        self._require_active_team(team_id)
        released_messages = tuple(self._inbox_repository.recover_reserved(team_id=team_id))
        recovered_assignments: list[TeamAssignment] = []
        for assignment in self._assignment_repository.list_for_team(team_id):
            if assignment.status is not TeamAssignmentStatus.IN_PROGRESS:
                continue
            recovered = assignment.mark_recovery_pending(
                reason="进程启动时发现未结束的 Team 工作分配。",
                occurred_at=self._clock.now(),
            )
            self._assignment_repository.replace(recovered)
            recovered_assignments.append(recovered)
        return TeamRecoveryResult(
            released_messages=released_messages,
            recovery_pending_assignments=tuple(recovered_assignments),
        )

    def _send_assignment_message(self, assignment: TeamAssignment) -> TeamMessage:
        """让收件箱消息只承担投递提示，分配事实始终以 Assignment 快照为准。"""

        return self._inbox_repository.send(
            TeamMessageDraft.create(
                message_id=f"assignment-message-{assignment.assignment_id}",
                team_id=assignment.team_id,
                sender_member_id=assignment.assigned_by_member_id,
                recipient_member_id=assignment.assignee_member_id,
                message_type=TeamMessageType.ASSIGNMENT,
                content=assignment.prompt,
                idempotency_key=f"assignment:{assignment.assignment_id}",
                created_at=self._clock.now(),
            )
        )

    def _require_active_team(self, team_id: str) -> Team:
        team = self._team_repository.get(team_id)
        if team is None:
            raise TeamEntityNotFoundError(entity_name="Team", entity_id=team_id)
        if team.status is not TeamStatus.ACTIVE:
            raise ValueError(f"Team“{team_id}”不是活动状态。")
        return team

    def _require_active_member(self, team_id: str, member_id: str) -> TeamMember:
        self._require_active_team(team_id)
        member = self._member_repository.get(member_id)
        if member is None:
            raise TeamEntityNotFoundError(entity_name="Team 成员", entity_id=member_id)
        if member.team_id != team_id:
            raise ValueError(f"成员“{member_id}”不属于 Team“{team_id}”。")
        if member.status is not TeamMemberStatus.ACTIVE:
            raise ValueError(f"成员“{member_id}”不是活动状态。")
        return member

    @staticmethod
    def _require_same_assignment_request(
        assignment: TeamAssignment,
        *,
        team_id: str,
        assigned_by_member_id: str,
        assignee_member_id: str,
        prompt: str,
        project_task_id: str | None,
    ) -> None:
        """只允许同一稳定 Assignment 标识重放同一个派活事实。"""

        if (
            assignment.team_id != team_id
            or assignment.assigned_by_member_id != assigned_by_member_id
            or assignment.assignee_member_id != assignee_member_id
            or assignment.prompt != prompt
            or assignment.project_task_id != project_task_id
        ):
            raise ValueError("同一工作分配标识不能表达不同的派活请求。")

    def _require_active_member_for_session(
        self,
        *,
        team_id: str,
        member_id: str,
        session_id: str,
    ) -> TeamMember:
        """把可变的当前工具上下文显式校验为该成员持久绑定的 Session。"""

        member = self._require_active_member(team_id, member_id)
        if member.session_id != session_id:
            raise ValueError(f"成员“{member_id}”不属于当前 Session。")
        return member
