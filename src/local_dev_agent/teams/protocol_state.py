"""S16 Team 请求状态及纯响应匹配规则。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from local_dev_agent.domain.state.timestamps import normalize_utc_timestamp

from .errors import (
    TeamProtocolAlreadyResolvedError,
    TeamProtocolMessageTypeMismatchError,
    TeamProtocolParticipantMismatchError,
    TeamProtocolPayloadMismatchError,
    TeamProtocolRequestIdMismatchError,
)
from .protocol_types import (
    TeamMessageType,
    TeamProtocolDecision,
    TeamProtocolStatus,
    TeamProtocolType,
    protocol_request_message_type,
    protocol_response_message_type,
)
from .schema import TeamMessage


def _require_nonempty_text(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


@dataclass(frozen=True, slots=True)
class TeamProtocolState:
    """一项可持久追踪的 Team 协议请求及其最终响应关联。"""

    request_id: str
    team_id: str
    protocol_type: TeamProtocolType
    sender_member_id: str
    target_member_id: str
    status: TeamProtocolStatus
    payload: str
    created_at: datetime
    decision: TeamProtocolDecision | None = None
    response_message_id: str | None = None
    response_content: str | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        """固定请求参与方和决议字段，防止 pending 与终态事实混用。"""

        for field_name in (
            "request_id",
            "team_id",
            "sender_member_id",
            "target_member_id",
            "payload",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_nonempty_text(field_name, getattr(self, field_name)),
            )
        if self.sender_member_id == self.target_member_id:
            raise ValueError("协议请求发送方和目标成员不能是同一成员。")
        if not isinstance(self.protocol_type, TeamProtocolType):
            raise ValueError("字段“protocol_type”必须是 TeamProtocolType。")
        if not isinstance(self.status, TeamProtocolStatus):
            raise ValueError("字段“status”必须是 TeamProtocolStatus。")
        object.__setattr__(
            self,
            "created_at",
            normalize_utc_timestamp(self.created_at, subject="Team 协议请求"),
        )
        if self.decision is not None and not isinstance(
            self.decision,
            TeamProtocolDecision,
        ):
            raise ValueError("字段“decision”必须是 TeamProtocolDecision 或 None。")
        if self.response_message_id is not None:
            object.__setattr__(
                self,
                "response_message_id",
                _require_nonempty_text("response_message_id", self.response_message_id),
            )
        if self.response_content is not None:
            object.__setattr__(
                self,
                "response_content",
                _require_nonempty_text("response_content", self.response_content),
            )
        if self.resolved_at is not None:
            object.__setattr__(
                self,
                "resolved_at",
                normalize_utc_timestamp(self.resolved_at, subject="Team 协议请求"),
            )
        self._validate_lifecycle_fields()

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        team_id: str,
        protocol_type: TeamProtocolType,
        sender_member_id: str,
        target_member_id: str,
        payload: str,
        created_at: datetime | None = None,
    ) -> TeamProtocolState:
        """创建等待响应的协议请求，不发送消息或访问任何仓储。"""

        return cls(
            request_id=request_id,
            team_id=team_id,
            protocol_type=protocol_type,
            sender_member_id=sender_member_id,
            target_member_id=target_member_id,
            status=TeamProtocolStatus.PENDING,
            payload=payload,
            created_at=created_at or datetime.now(timezone.utc),
        )

    @property
    def request_message_type(self) -> TeamMessageType:
        """返回该协议唯一合法的请求消息类型。"""

        return protocol_request_message_type(self.protocol_type)

    @property
    def response_message_type(self) -> TeamMessageType:
        """返回该协议唯一合法的响应消息类型。"""

        return protocol_response_message_type(self.protocol_type)

    def validate_request_message(self, message: TeamMessage) -> None:
        """校验投递请求与本状态一致，不改变 pending 状态。"""

        self._validate_message(
            message,
            expected_type=self.request_message_type,
            expected_sender=self.sender_member_id,
            expected_recipient=self.target_member_id,
        )
        if message.content != self.payload:
            raise TeamProtocolPayloadMismatchError(request_id=self.request_id)

    def match_response(self, message: TeamMessage) -> TeamProtocolState:
        """匹配反向响应并产生终态；完全相同的重复响应保持幂等。"""

        self._validate_message(
            message,
            expected_type=self.response_message_type,
            expected_sender=self.target_member_id,
            expected_recipient=self.sender_member_id,
        )
        decision = message.protocol_decision
        if decision is None:
            raise AssertionError("协议响应通过消息契约后必须包含决议。")
        if self.status is not TeamProtocolStatus.PENDING:
            if (
                self.response_message_id == message.message_id
                and self.decision is decision
                and self.response_content == message.content
                and self.resolved_at == message.created_at
            ):
                return self
            raise TeamProtocolAlreadyResolvedError(
                request_id=self.request_id,
                status=self.status.value,
            )
        return replace(
            self,
            status=(
                TeamProtocolStatus.APPROVED
                if decision is TeamProtocolDecision.APPROVED
                else TeamProtocolStatus.REJECTED
            ),
            decision=decision,
            response_message_id=message.message_id,
            response_content=message.content,
            resolved_at=message.created_at,
        )

    def _validate_message(
        self,
        message: TeamMessage,
        *,
        expected_type: TeamMessageType,
        expected_sender: str,
        expected_recipient: str,
    ) -> None:
        if not isinstance(message, TeamMessage):
            raise TypeError("message 必须是 TeamMessage 对象。")
        if message.request_id != self.request_id:
            raise TeamProtocolRequestIdMismatchError(
                expected_request_id=self.request_id,
                actual_request_id=message.request_id or "<缺失>",
            )
        if message.message_type is not expected_type:
            raise TeamProtocolMessageTypeMismatchError(
                request_id=self.request_id,
                expected_message_type=expected_type.value,
                actual_message_type=message.message_type.value,
            )
        if (
            message.team_id != self.team_id
            or message.sender_member_id != expected_sender
            or message.recipient_member_id != expected_recipient
        ):
            raise TeamProtocolParticipantMismatchError(request_id=self.request_id)

    def _validate_lifecycle_fields(self) -> None:
        if self.status is TeamProtocolStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.decision,
                    self.response_message_id,
                    self.response_content,
                    self.resolved_at,
                )
            ):
                raise ValueError("待响应协议请求不能包含决议或响应关联。")
            return
        if (
            self.decision is None
            or self.response_message_id is None
            or self.response_content is None
            or self.resolved_at is None
        ):
            raise ValueError("已决协议请求必须包含决议、响应消息和解决时间。")
        expected_status = (
            TeamProtocolStatus.APPROVED
            if self.decision is TeamProtocolDecision.APPROVED
            else TeamProtocolStatus.REJECTED
        )
        if self.status is not expected_status:
            raise ValueError("协议请求状态必须与响应决议一致。")
        if self.resolved_at < self.created_at:
            raise ValueError("字段“resolved_at”不能早于“created_at”。")
