"""S15 Team 协作与 S16 结构化协议的不可变领域契约。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable
from uuid import uuid4

from local_dev_agent.domain.state.timestamps import normalize_utc_timestamp

from .errors import (
    InvalidTeamAssignmentTransitionError,
    InvalidTeamMessageTransitionError,
)
from .protocol_types import (
    TeamMessageType,
    TeamProtocolDecision,
    is_protocol_request_message_type,
    is_protocol_response_message_type,
)


def _require_nonempty_text(field_name: str, value: str) -> str:
    """拒绝不能可靠标识、路由或展示的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


class TeamStatus(StrEnum):
    """Team 定义的持久生命周期，不表示任何进程线程是否存活。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class TeamMemberStatus(StrEnum):
    """成员在 Team 中的持久资格，不承担 Runner 的瞬时状态。"""

    ACTIVE = "active"
    INACTIVE = "inactive"


class TeamAssignmentStatus(StrEnum):
    """一项 Team 工作分配的可恢复生命周期。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RECOVERY_PENDING = "recovery_pending"
    COMPLETED = "completed"
    FAILED = "failed"


class TeamMessageDeliveryStatus(StrEnum):
    """消息从未读到确认消费的持久投递状态。"""

    UNREAD = "unread"
    RESERVED = "reserved"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class TeamAutonomousWorkItem:
    """成员自主认领后交给 Runtime 的最小项目任务事实。"""

    task_id: str
    subject: str
    description: str

    def __post_init__(self) -> None:
        """冻结已认领任务的展示内容，避免 Runner 依赖 S12 的具体模型。"""

        object.__setattr__(self, "task_id", _require_nonempty_text("task_id", self.task_id))
        object.__setattr__(self, "subject", _require_nonempty_text("subject", self.subject))
        if not isinstance(self.description, str):
            raise ValueError("字段“description”必须是字符串。")


def _normalize_protocol_message_fields(
    *,
    message_type: TeamMessageType,
    request_id: str | None,
    protocol_decision: TeamProtocolDecision | None,
) -> tuple[str | None, TeamProtocolDecision | None]:
    """让协议关联字段只出现在合法的 request 或 response 消息上。"""

    is_request = is_protocol_request_message_type(message_type)
    is_response = is_protocol_response_message_type(message_type)
    if not is_request and not is_response:
        if request_id is not None or protocol_decision is not None:
            raise ValueError("普通 Team 消息不能包含协议 request_id 或决议。")
        return None, None
    if request_id is None:
        raise ValueError("协议消息必须包含非空 request_id。")
    normalized_request_id = _require_nonempty_text("request_id", request_id)
    if is_request:
        if protocol_decision is not None:
            raise ValueError("协议请求消息不能提前包含响应决议。")
        return normalized_request_id, None
    if not isinstance(protocol_decision, TeamProtocolDecision):
        raise ValueError("协议响应消息必须包含 TeamProtocolDecision。")
    return normalized_request_id, protocol_decision


@dataclass(frozen=True, slots=True)
class TeamMessageDraft:
    """等待收件箱分配 sequence 后才成为正式消息的投递请求。"""

    message_id: str
    team_id: str
    sender_member_id: str
    recipient_member_id: str
    message_type: TeamMessageType
    content: str
    idempotency_key: str
    created_at: datetime
    request_id: str | None = None
    protocol_decision: TeamProtocolDecision | None = None

    def __post_init__(self) -> None:
        """将发送方和接收方事实固定下来，把顺序分配留给加锁的收件箱。"""

        for field_name in (
            "message_id",
            "team_id",
            "sender_member_id",
            "recipient_member_id",
            "content",
            "idempotency_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_nonempty_text(field_name, getattr(self, field_name)),
            )
        if self.sender_member_id == self.recipient_member_id:
            raise ValueError("消息发送方和接收方不能是同一成员。")
        if not isinstance(self.message_type, TeamMessageType):
            raise ValueError("字段“message_type”必须是 TeamMessageType。")
        request_id, decision = _normalize_protocol_message_fields(
            message_type=self.message_type,
            request_id=self.request_id,
            protocol_decision=self.protocol_decision,
        )
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "protocol_decision", decision)
        object.__setattr__(
            self,
            "created_at",
            normalize_utc_timestamp(self.created_at, subject="Team 消息草稿"),
        )

    @classmethod
    def create(
        cls,
        *,
        team_id: str,
        sender_member_id: str,
        recipient_member_id: str,
        message_type: TeamMessageType,
        content: str,
        idempotency_key: str,
        message_id: str | None = None,
        created_at: datetime | None = None,
        request_id: str | None = None,
        protocol_decision: TeamProtocolDecision | None = None,
    ) -> "TeamMessageDraft":
        """创建未分配 sequence 的投递草稿。"""

        return cls(
            message_id=message_id or str(uuid4()),
            team_id=team_id,
            sender_member_id=sender_member_id,
            recipient_member_id=recipient_member_id,
            message_type=message_type,
            content=content,
            idempotency_key=idempotency_key,
            created_at=created_at or datetime.now(timezone.utc),
            request_id=request_id,
            protocol_decision=protocol_decision,
        )


@dataclass(frozen=True, slots=True)
class Team:
    """一个工作区中的协作边界，只保存 Team 身份和 Lead 成员关联。"""

    team_id: str
    workspace_id: str
    lead_member_id: str
    status: TeamStatus
    created_at: datetime

    def __post_init__(self) -> None:
        """冻结持久 Team 身份，避免把进程运行状态混入配置快照。"""

        object.__setattr__(self, "team_id", _require_nonempty_text("team_id", self.team_id))
        object.__setattr__(
            self,
            "workspace_id",
            _require_nonempty_text("workspace_id", self.workspace_id),
        )
        object.__setattr__(
            self,
            "lead_member_id",
            _require_nonempty_text("lead_member_id", self.lead_member_id),
        )
        if not isinstance(self.status, TeamStatus):
            raise ValueError("字段“status”必须是 TeamStatus。")
        object.__setattr__(
            self,
            "created_at",
            normalize_utc_timestamp(self.created_at, subject="Team"),
        )

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        lead_member_id: str,
        team_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "Team":
        """创建活动 Team；成员目录由独立仓储保存。"""

        return cls(
            team_id=team_id or str(uuid4()),
            workspace_id=workspace_id,
            lead_member_id=lead_member_id,
            status=TeamStatus.ACTIVE,
            created_at=created_at or datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class TeamMember:
    """Team 内稳定成员身份及其独立 Agent Session 绑定。"""

    member_id: str
    team_id: str
    name: str
    role: str
    session_id: str
    status: TeamMemberStatus
    created_at: datetime

    def __post_init__(self) -> None:
        """将身份、角色和 Session 绑定保存为可恢复快照。"""

        for field_name in ("member_id", "team_id", "name", "role", "session_id"):
            object.__setattr__(
                self,
                field_name,
                _require_nonempty_text(field_name, getattr(self, field_name)),
            )
        if not isinstance(self.status, TeamMemberStatus):
            raise ValueError("字段“status”必须是 TeamMemberStatus。")
        object.__setattr__(
            self,
            "created_at",
            normalize_utc_timestamp(self.created_at, subject="Team 成员"),
        )

    @classmethod
    def create(
        cls,
        *,
        team_id: str,
        name: str,
        role: str,
        session_id: str,
        member_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "TeamMember":
        """创建活动成员；线程和当前 Run 仍属于后续基础设施。"""

        return cls(
            member_id=member_id or str(uuid4()),
            team_id=team_id,
            name=name,
            role=role,
            session_id=session_id,
            status=TeamMemberStatus.ACTIVE,
            created_at=created_at or datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class TeamAssignment:
    """独立于 S12 项目任务的一项 Team 工作分配。"""

    assignment_id: str
    team_id: str
    assigned_by_member_id: str
    assignee_member_id: str
    prompt: str
    status: TeamAssignmentStatus
    created_at: datetime
    updated_at: datetime
    project_task_id: str | None = None
    attempt: int = 0
    last_run_id: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        """收束 Assignment 的追溯字段，并保留 S12 外键的显式可选性。"""

        for field_name in (
            "assignment_id",
            "team_id",
            "assigned_by_member_id",
            "assignee_member_id",
            "prompt",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_nonempty_text(field_name, getattr(self, field_name)),
            )
        if not isinstance(self.status, TeamAssignmentStatus):
            raise ValueError("字段“status”必须是 TeamAssignmentStatus。")
        object.__setattr__(
            self,
            "created_at",
            normalize_utc_timestamp(self.created_at, subject="Team 工作分配"),
        )
        object.__setattr__(
            self,
            "updated_at",
            normalize_utc_timestamp(self.updated_at, subject="Team 工作分配"),
        )
        if self.updated_at < self.created_at:
            raise ValueError("字段“updated_at”不能早于“created_at”。")
        if self.project_task_id is not None:
            object.__setattr__(
                self,
                "project_task_id",
                _require_nonempty_text("project_task_id", self.project_task_id),
            )
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("字段“attempt”必须是非负整数。")
        if self.last_run_id is not None:
            object.__setattr__(
                self,
                "last_run_id",
                _require_nonempty_text("last_run_id", self.last_run_id),
            )
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _require_nonempty_text("failure_reason", self.failure_reason),
            )
        self._validate_lifecycle_fields()

    @classmethod
    def create(
        cls,
        *,
        team_id: str,
        assigned_by_member_id: str,
        assignee_member_id: str,
        prompt: str,
        project_task_id: str | None = None,
        assignment_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "TeamAssignment":
        """创建未开始的分配，不自动认领或修改 S12 项目任务。"""

        timestamp = created_at or datetime.now(timezone.utc)
        return cls(
            assignment_id=assignment_id or str(uuid4()),
            team_id=team_id,
            assigned_by_member_id=assigned_by_member_id,
            assignee_member_id=assignee_member_id,
            prompt=prompt,
            status=TeamAssignmentStatus.PENDING,
            created_at=timestamp,
            updated_at=timestamp,
            project_task_id=project_task_id,
        )

    def start(self, *, run_id: str, occurred_at: datetime) -> "TeamAssignment":
        """关联将要执行的独立 Run，并递增可诊断的执行尝试次数。"""

        self._require_status(
            {TeamAssignmentStatus.PENDING, TeamAssignmentStatus.RECOVERY_PENDING},
            TeamAssignmentStatus.IN_PROGRESS,
        )
        return replace(
            self,
            status=TeamAssignmentStatus.IN_PROGRESS,
            updated_at=occurred_at,
            attempt=self.attempt + 1,
            last_run_id=run_id,
            failure_reason=None,
        )

    def mark_recovery_pending(
        self,
        *,
        reason: str,
        occurred_at: datetime,
    ) -> "TeamAssignment":
        """将进程中断的执行显式保留为待恢复，而不伪造完成结果。"""

        self._require_status(
            {TeamAssignmentStatus.IN_PROGRESS},
            TeamAssignmentStatus.RECOVERY_PENDING,
        )
        return replace(
            self,
            status=TeamAssignmentStatus.RECOVERY_PENDING,
            updated_at=occurred_at,
            failure_reason=reason,
        )

    def complete(self, *, occurred_at: datetime) -> "TeamAssignment":
        """记录 Team 分配完成，不越过 S12 自动完成项目任务。"""

        self._require_status({TeamAssignmentStatus.IN_PROGRESS}, TeamAssignmentStatus.COMPLETED)
        return replace(
            self,
            status=TeamAssignmentStatus.COMPLETED,
            updated_at=occurred_at,
            failure_reason=None,
        )

    def fail(self, *, reason: str, occurred_at: datetime) -> "TeamAssignment":
        """记录一次已终止的执行失败，保留原因供 Lead 后续判断。"""

        self._require_status({TeamAssignmentStatus.IN_PROGRESS}, TeamAssignmentStatus.FAILED)
        return replace(
            self,
            status=TeamAssignmentStatus.FAILED,
            updated_at=occurred_at,
            failure_reason=reason,
        )

    def _require_status(
        self,
        allowed_statuses: set[TeamAssignmentStatus],
        target_status: TeamAssignmentStatus,
    ) -> None:
        if self.status not in allowed_statuses:
            raise InvalidTeamAssignmentTransitionError(
                assignment_id=self.assignment_id,
                status=self.status.value,
                target_status=target_status.value,
            )

    def _validate_lifecycle_fields(self) -> None:
        """确保恢复、运行和终态字段不把不同生命周期事实混在一起。"""

        if self.status is TeamAssignmentStatus.PENDING:
            if self.attempt != 0 or self.last_run_id is not None or self.failure_reason is not None:
                raise ValueError("待处理工作分配不能包含执行、Run 或失败信息。")
            return
        if self.status is TeamAssignmentStatus.IN_PROGRESS:
            if self.attempt < 1 or self.last_run_id is None or self.failure_reason is not None:
                raise ValueError("执行中的工作分配必须关联 Run，且不能包含失败原因。")
            return
        if self.status is TeamAssignmentStatus.RECOVERY_PENDING:
            if self.attempt < 1 or self.last_run_id is None or self.failure_reason is None:
                raise ValueError("待恢复工作分配必须保留中断 Run 和原因。")
            return
        if self.status is TeamAssignmentStatus.COMPLETED:
            if self.attempt < 1 or self.last_run_id is None or self.failure_reason is not None:
                raise ValueError("已完成工作分配必须关联 Run，且不能包含失败原因。")
            return
        if self.attempt < 1 or self.last_run_id is None or self.failure_reason is None:
            raise ValueError("失败工作分配必须关联 Run 和失败原因。")


@dataclass(frozen=True, slots=True)
class TeamMessage:
    """一个有发送方、接收方、顺序和消费状态的 Team 收件箱事实。"""

    message_id: str
    team_id: str
    sender_member_id: str
    recipient_member_id: str
    sequence: int
    message_type: TeamMessageType
    content: str
    idempotency_key: str
    created_at: datetime
    delivery_status: TeamMessageDeliveryStatus
    reservation_id: str | None = None
    reserved_at: datetime | None = None
    consumed_by_session_id: str | None = None
    consumed_by_run_id: str | None = None
    consumed_at: datetime | None = None
    request_id: str | None = None
    protocol_decision: TeamProtocolDecision | None = None

    def __post_init__(self) -> None:
        """明确消息投递的全部身份和状态，避免收件箱依赖文件顺序猜测事实。"""

        for field_name in (
            "message_id",
            "team_id",
            "sender_member_id",
            "recipient_member_id",
            "content",
            "idempotency_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_nonempty_text(field_name, getattr(self, field_name)),
            )
        if self.sender_member_id == self.recipient_member_id:
            raise ValueError("消息发送方和接收方不能是同一成员。")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("字段“sequence”必须是正整数。")
        if not isinstance(self.message_type, TeamMessageType):
            raise ValueError("字段“message_type”必须是 TeamMessageType。")
        request_id, decision = _normalize_protocol_message_fields(
            message_type=self.message_type,
            request_id=self.request_id,
            protocol_decision=self.protocol_decision,
        )
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "protocol_decision", decision)
        if not isinstance(self.delivery_status, TeamMessageDeliveryStatus):
            raise ValueError("字段“delivery_status”必须是 TeamMessageDeliveryStatus。")
        object.__setattr__(
            self,
            "created_at",
            normalize_utc_timestamp(self.created_at, subject="Team 消息"),
        )
        for field_name in ("reservation_id", "consumed_by_session_id", "consumed_by_run_id"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _require_nonempty_text(field_name, value))
        for field_name in ("reserved_at", "consumed_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    normalize_utc_timestamp(value, subject="Team 消息"),
                )
        self._validate_delivery_fields()

    @classmethod
    def create(
        cls,
        *,
        team_id: str,
        sender_member_id: str,
        recipient_member_id: str,
        sequence: int,
        message_type: TeamMessageType,
        content: str,
        idempotency_key: str,
        message_id: str | None = None,
        created_at: datetime | None = None,
        request_id: str | None = None,
        protocol_decision: TeamProtocolDecision | None = None,
    ) -> "TeamMessage":
        """创建已分配顺序的未读消息，仅供收件箱仓储内部使用。"""

        return cls(
            message_id=message_id or str(uuid4()),
            team_id=team_id,
            sender_member_id=sender_member_id,
            recipient_member_id=recipient_member_id,
            sequence=sequence,
            message_type=message_type,
            content=content,
            idempotency_key=idempotency_key,
            created_at=created_at or datetime.now(timezone.utc),
            delivery_status=TeamMessageDeliveryStatus.UNREAD,
            request_id=request_id,
            protocol_decision=protocol_decision,
        )

    def reserve(self, *, reservation_id: str, occurred_at: datetime) -> "TeamMessage":
        """在启动 Agent Run 前预留消息，避免多个 worker 同时消费。"""

        self._require_delivery_status(TeamMessageDeliveryStatus.UNREAD, "预留")
        return replace(
            self,
            delivery_status=TeamMessageDeliveryStatus.RESERVED,
            reservation_id=reservation_id,
            reserved_at=occurred_at,
        )

    def release(self) -> "TeamMessage":
        """在执行失败或进程恢复时释放预留，使消息能够至少一次重投。"""

        self._require_delivery_status(TeamMessageDeliveryStatus.RESERVED, "释放预留")
        return replace(
            self,
            delivery_status=TeamMessageDeliveryStatus.UNREAD,
            reservation_id=None,
            reserved_at=None,
        )

    def consume(
        self,
        *,
        reservation_id: str,
        session_id: str,
        run_id: str,
        occurred_at: datetime,
    ) -> "TeamMessage":
        """仅确认本次预留的消息，记录真正接收消息的 Session 与 Run。"""

        self._require_delivery_status(TeamMessageDeliveryStatus.RESERVED, "确认消费")
        if self.reservation_id != _require_nonempty_text("reservation_id", reservation_id):
            raise InvalidTeamMessageTransitionError(
                message_id=self.message_id,
                status=self.delivery_status.value,
                action="确认其他预留",
            )
        return replace(
            self,
            delivery_status=TeamMessageDeliveryStatus.CONSUMED,
            consumed_by_session_id=session_id,
            consumed_by_run_id=run_id,
            consumed_at=occurred_at,
        )

    def _require_delivery_status(
        self,
        expected_status: TeamMessageDeliveryStatus,
        action: str,
    ) -> None:
        if self.delivery_status is not expected_status:
            raise InvalidTeamMessageTransitionError(
                message_id=self.message_id,
                status=self.delivery_status.value,
                action=action,
            )

    def _validate_delivery_fields(self) -> None:
        """防止未读、预留和已消费消息混用彼此专属的关联字段。"""

        if self.delivery_status is TeamMessageDeliveryStatus.UNREAD:
            if any(
                value is not None
                for value in (
                    self.reservation_id,
                    self.reserved_at,
                    self.consumed_by_session_id,
                    self.consumed_by_run_id,
                    self.consumed_at,
                )
            ):
                raise ValueError("未读消息不能包含预留或消费信息。")
            return
        if self.delivery_status is TeamMessageDeliveryStatus.RESERVED:
            if self.reservation_id is None or self.reserved_at is None:
                raise ValueError("已预留消息必须包含预留标识和时间。")
            if any(
                value is not None
                for value in (
                    self.consumed_by_session_id,
                    self.consumed_by_run_id,
                    self.consumed_at,
                )
            ):
                raise ValueError("已预留消息不能包含消费信息。")
            return
        if (
            self.reservation_id is None
            or self.reserved_at is None
            or self.consumed_by_session_id is None
            or self.consumed_by_run_id is None
            or self.consumed_at is None
        ):
            raise ValueError("已消费消息必须保留预留与消费关联信息。")
        if self.consumed_at < self.reserved_at:
            raise ValueError("字段“consumed_at”不能早于“reserved_at”。")


@dataclass(frozen=True, slots=True)
class InboxReservation:
    """同一收件箱的一批已预留消息，作为后续确认或释放的原子边界。"""

    team_id: str
    recipient_member_id: str
    reservation_id: str
    messages: tuple[TeamMessage, ...]
    reserved_at: datetime

    def __post_init__(self) -> None:
        """确保一个 reservation 不会混入其他 Team、接收方或投递状态。"""

        for field_name in ("team_id", "recipient_member_id", "reservation_id"):
            object.__setattr__(
                self,
                field_name,
                _require_nonempty_text(field_name, getattr(self, field_name)),
            )
        if not isinstance(self.messages, tuple) or not self.messages:
            raise ValueError("字段“messages”必须是非空 TeamMessage 元组。")
        if not all(isinstance(message, TeamMessage) for message in self.messages):
            raise ValueError("字段“messages”必须只包含 TeamMessage。")
        sequences = tuple(message.sequence for message in self.messages)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
            raise ValueError("预留消息必须按不重复 sequence 升序排列。")
        if not all(
            message.team_id == self.team_id
            and message.recipient_member_id == self.recipient_member_id
            and message.delivery_status is TeamMessageDeliveryStatus.RESERVED
            and message.reservation_id == self.reservation_id
            for message in self.messages
        ):
            raise ValueError("预留消息必须属于同一 Team、接收方和 reservation。")
        object.__setattr__(
            self,
            "reserved_at",
            normalize_utc_timestamp(self.reserved_at, subject="收件箱预留"),
        )
        if any(message.reserved_at != self.reserved_at for message in self.messages):
            raise ValueError("预留消息必须使用同一个预留时间。")

    def subset(self, messages: Iterable[TeamMessage]) -> "InboxReservation":
        """从同一次预留中划出子批次，供协议消息和 Agent 消息分别确认或释放。"""

        selected_messages = tuple(messages)
        if not selected_messages:
            raise ValueError("预留消息子集不能为空。")
        if not all(isinstance(message, TeamMessage) for message in selected_messages):
            raise TypeError("预留消息子集只能包含 TeamMessage。")
        selected_ids = tuple(message.message_id for message in selected_messages)
        original_by_id = {message.message_id: message for message in self.messages}
        if len(set(selected_ids)) != len(selected_ids) or any(
            message_id not in original_by_id for message_id in selected_ids
        ):
            raise ValueError("预留消息子集必须是不重复的原预留消息。")
        ordered_messages = tuple(
            message for message in self.messages if message.message_id in set(selected_ids)
        )
        return replace(self, messages=ordered_messages)


@dataclass(frozen=True, slots=True)
class TeamPromptExecution:
    """Runner 通过现有 Runtime 执行一次成员 Run 后返回的最小事实。"""

    session_id: str
    run_id: str
    response_text: str

    def __post_init__(self) -> None:
        """只保留后续确认消息消费与汇报结果所需的稳定信息。"""

        object.__setattr__(
            self,
            "session_id",
            _require_nonempty_text("session_id", self.session_id),
        )
        object.__setattr__(self, "run_id", _require_nonempty_text("run_id", self.run_id))
        if not isinstance(self.response_text, str):
            raise ValueError("字段“response_text”必须是字符串。")


@dataclass(frozen=True, slots=True)
class TeamAutonomousWorkOutcome:
    """自主工作一次执行后的核验结论，供后续 RESULT 回传使用。"""

    work_item: TeamAutonomousWorkItem
    execution: TeamPromptExecution | None
    completed: bool
    detail: str

    def __post_init__(self) -> None:
        """区分模型执行事实和任务完成事实，避免自由文本被误判为完成。"""

        if not isinstance(self.work_item, TeamAutonomousWorkItem):
            raise TypeError("work_item 必须是 TeamAutonomousWorkItem 对象。")
        if self.execution is not None and not isinstance(self.execution, TeamPromptExecution):
            raise TypeError("execution 必须是 TeamPromptExecution 对象或空值。")
        if not isinstance(self.completed, bool):
            raise TypeError("completed 必须是布尔值。")
        if not isinstance(self.detail, str):
            raise ValueError("字段“detail”必须是字符串。")


def freeze_messages(messages: Iterable[TeamMessage]) -> tuple[TeamMessage, ...]:
    """复制消息集合，供适配器构造稳定批次而不暴露可变容器。"""

    frozen_messages = tuple(messages)
    if not all(isinstance(message, TeamMessage) for message in frozen_messages):
        raise TypeError("messages 必须只包含 TeamMessage。")
    return frozen_messages
