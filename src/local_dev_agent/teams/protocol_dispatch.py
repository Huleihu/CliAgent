"""S16 Team 协议请求创建、响应投递与按类型 dispatch 的应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import (
    TeamProtocolError,
    TeamProtocolParticipantMismatchError,
    TeamProtocolRequestConflictError,
    UnknownTeamProtocolRequestError,
)
from .ports import TeamClock, TeamInboxRepository, TeamProtocolStateRepository
from .protocol_state import TeamProtocolState
from .protocol_types import (
    TeamMessageType,
    TeamProtocolDecision,
    TeamProtocolStatus,
)
from .schema import TeamMessage, TeamMessageDraft


class TeamProtocolDispatchDisposition(StrEnum):
    """协议消息经确定性处理后的下一步，不表示实际 Runner 已执行。"""

    FORWARD_TO_AGENT = "forward_to_agent"
    HANDLED = "handled"
    STOP_MEMBER = "stop_member"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TeamProtocolDispatchResult:
    """协议 dispatch 的结构化结论，供后续 Runner 决定确认消费或创建 Run。"""

    message: TeamMessage
    disposition: TeamProtocolDispatchDisposition
    state: TeamProtocolState | None = None
    emitted_messages: tuple[TeamMessage, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        """让失败结果显式携带原因，成功结果不混入失败诊断。"""

        if not isinstance(self.message, TeamMessage):
            raise TypeError("message 必须是 TeamMessage 对象。")
        if not isinstance(self.disposition, TeamProtocolDispatchDisposition):
            raise ValueError("字段“disposition”必须是 TeamProtocolDispatchDisposition。")
        if self.state is not None and not isinstance(self.state, TeamProtocolState):
            raise TypeError("state 必须是 TeamProtocolState 对象或 None。")
        if not isinstance(self.emitted_messages, tuple) or not all(
            isinstance(message, TeamMessage) for message in self.emitted_messages
        ):
            raise TypeError("emitted_messages 必须是 TeamMessage 元组。")
        if self.disposition is TeamProtocolDispatchDisposition.FAILED:
            if not isinstance(self.failure_reason, str) or not self.failure_reason.strip():
                raise ValueError("协议失败结果必须包含非空 failure_reason。")
            return
        if self.failure_reason is not None:
            raise ValueError("非失败协议结果不能包含 failure_reason。")

    @property
    def should_forward_to_agent(self) -> bool:
        """后续 Runner 是否应把该消息交给既有 Runtime 创建 Run。"""

        return self.disposition is TeamProtocolDispatchDisposition.FORWARD_TO_AGENT


class TeamProtocolCoordinator:
    """协调协议状态和收件箱投递，不依赖 Runner、Runtime 或 CLI。"""

    def __init__(
        self,
        *,
        state_repository: TeamProtocolStateRepository,
        inbox_repository: TeamInboxRepository,
        clock: TeamClock,
    ) -> None:
        if not all(
            callable(getattr(state_repository, method_name, None))
            for method_name in ("add", "get", "replace")
        ):
            raise TypeError("state_repository 必须提供新增、查询和替换方法。")
        if not callable(getattr(inbox_repository, "send", None)):
            raise TypeError("inbox_repository 必须提供 send 方法。")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须提供 now 方法。")
        self._state_repository = state_repository
        self._inbox_repository = inbox_repository
        self._clock = clock

    def open_request(
        self,
        *,
        state: TeamProtocolState,
        message_id: str,
        idempotency_key: str,
    ) -> tuple[TeamProtocolState, TeamMessage]:
        """保存 pending 请求并投递 request；相同请求重放不会产生第二条消息。"""

        if not isinstance(state, TeamProtocolState):
            raise TypeError("state 必须是 TeamProtocolState 对象。")
        if state.status is not TeamProtocolStatus.PENDING:
            raise ValueError("只能创建等待响应的 Team 协议请求。")
        existing = self._state_repository.get(state.request_id)
        if existing is None:
            persisted_state = self._state_repository.add(state)
        else:
            self._require_same_request(existing, state)
            persisted_state = existing
        message = self._inbox_repository.send(
            TeamMessageDraft.create(
                message_id=message_id,
                team_id=persisted_state.team_id,
                sender_member_id=persisted_state.sender_member_id,
                recipient_member_id=persisted_state.target_member_id,
                message_type=persisted_state.request_message_type,
                content=persisted_state.payload,
                idempotency_key=idempotency_key,
                request_id=persisted_state.request_id,
                created_at=self._clock.now(),
            )
        )
        return persisted_state, message

    def send_response(
        self,
        *,
        request_id: str,
        sender_member_id: str,
        decision: TeamProtocolDecision,
        content: str,
        message_id: str,
        idempotency_key: str,
    ) -> TeamMessage:
        """按已登记请求反向投递 response；最终状态由接收方 dispatch 时匹配。"""

        state = self._require_state(request_id)
        if sender_member_id != state.target_member_id:
            raise TeamProtocolParticipantMismatchError(request_id=request_id)
        if not isinstance(decision, TeamProtocolDecision):
            raise ValueError("字段“decision”必须是 TeamProtocolDecision。")
        return self._inbox_repository.send(
            TeamMessageDraft.create(
                message_id=message_id,
                team_id=state.team_id,
                sender_member_id=sender_member_id,
                recipient_member_id=state.sender_member_id,
                message_type=state.response_message_type,
                content=content,
                idempotency_key=idempotency_key,
                request_id=state.request_id,
                protocol_decision=decision,
                created_at=self._clock.now(),
            )
        )

    def dispatch(self, message: TeamMessage) -> TeamProtocolDispatchResult:
        """按消息类型处理协议或透传既有 S15 消息，不把协议失败交给模型猜测。"""

        if not isinstance(message, TeamMessage):
            raise TypeError("message 必须是 TeamMessage 对象。")
        if message.message_type in {
            TeamMessageType.PLAIN,
            TeamMessageType.ASSIGNMENT,
            TeamMessageType.RESULT,
        }:
            return TeamProtocolDispatchResult(
                message=message,
                disposition=TeamProtocolDispatchDisposition.FORWARD_TO_AGENT,
            )
        try:
            if message.message_type is TeamMessageType.SHUTDOWN_REQUEST:
                return self._dispatch_shutdown_request(message)
            if message.message_type is TeamMessageType.SHUTDOWN_RESPONSE:
                return self._dispatch_shutdown_response(message)
            if message.message_type is TeamMessageType.PLAN_APPROVAL_REQUEST:
                return self._dispatch_plan_request(message)
            if message.message_type is TeamMessageType.PLAN_APPROVAL_RESPONSE:
                return self._dispatch_plan_response(message)
            return self._failure(message, "不支持的 Team 协议消息类型。")
        except TeamProtocolError as error:
            return self._failure(message, str(error))

    def _dispatch_shutdown_request(self, message: TeamMessage) -> TeamProtocolDispatchResult:
        state = self._require_state_for_request(message)
        response = self.send_response(
            request_id=state.request_id,
            sender_member_id=message.recipient_member_id,
            decision=TeamProtocolDecision.APPROVED,
            content="已确认安全停止当前 Team 成员 Runner。",
            message_id=f"shutdown-response-{message.message_id}",
            idempotency_key=f"shutdown-response:{message.message_id}",
        )
        return TeamProtocolDispatchResult(
            message=message,
            disposition=TeamProtocolDispatchDisposition.STOP_MEMBER,
            state=state,
            emitted_messages=(response,),
        )

    def _dispatch_shutdown_response(self, message: TeamMessage) -> TeamProtocolDispatchResult:
        state = self._match_response(message)
        return TeamProtocolDispatchResult(
            message=message,
            disposition=TeamProtocolDispatchDisposition.HANDLED,
            state=state,
        )

    def _dispatch_plan_request(self, message: TeamMessage) -> TeamProtocolDispatchResult:
        state = self._require_state_for_request(message)
        return TeamProtocolDispatchResult(
            message=message,
            disposition=TeamProtocolDispatchDisposition.FORWARD_TO_AGENT,
            state=state,
        )

    def _dispatch_plan_response(self, message: TeamMessage) -> TeamProtocolDispatchResult:
        state = self._match_response(message)
        return TeamProtocolDispatchResult(
            message=message,
            disposition=TeamProtocolDispatchDisposition.FORWARD_TO_AGENT,
            state=state,
        )

    def _require_state_for_request(self, message: TeamMessage) -> TeamProtocolState:
        state = self._require_state(message.request_id)
        state.validate_request_message(message)
        return state

    def _match_response(self, message: TeamMessage) -> TeamProtocolState:
        state = self._require_state(message.request_id)
        resolved = state.match_response(message)
        if resolved is not state:
            self._state_repository.replace(resolved)
        return resolved

    def _require_state(self, request_id: str | None) -> TeamProtocolState:
        if request_id is None:
            raise UnknownTeamProtocolRequestError(request_id="<缺失>")
        state = self._state_repository.get(request_id)
        if state is None:
            raise UnknownTeamProtocolRequestError(request_id=request_id)
        return state

    @staticmethod
    def _require_same_request(
        existing: TeamProtocolState,
        requested: TeamProtocolState,
    ) -> None:
        if (
            existing.team_id != requested.team_id
            or existing.protocol_type is not requested.protocol_type
            or existing.sender_member_id != requested.sender_member_id
            or existing.target_member_id != requested.target_member_id
            or existing.payload != requested.payload
        ):
            raise TeamProtocolRequestConflictError(request_id=requested.request_id)

    @staticmethod
    def _failure(message: TeamMessage, reason: str) -> TeamProtocolDispatchResult:
        return TeamProtocolDispatchResult(
            message=message,
            disposition=TeamProtocolDispatchDisposition.FAILED,
            failure_reason=reason,
        )
