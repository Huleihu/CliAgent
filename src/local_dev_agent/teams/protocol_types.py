"""Team 普通消息与 S16 结构化协议共享的类型映射。"""

from enum import StrEnum


class TeamMessageType(StrEnum):
    """Team 普通消息与 S16 结构化协议消息类别。"""

    PLAIN = "plain"
    ASSIGNMENT = "assignment"
    RESULT = "result"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_REQUEST = "plan_approval_request"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


class TeamProtocolType(StrEnum):
    """共享请求—响应状态机的协议类别。"""

    SHUTDOWN = "shutdown"
    PLAN_APPROVAL = "plan_approval"


class TeamProtocolStatus(StrEnum):
    """协议请求从等待响应到最终决议的生命周期。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TeamProtocolDecision(StrEnum):
    """响应消息携带的结构化决议，不从自由文本正文推断。"""

    APPROVED = "approved"
    REJECTED = "rejected"


_PROTOCOL_REQUEST_MESSAGE_TYPES = {
    TeamProtocolType.SHUTDOWN: TeamMessageType.SHUTDOWN_REQUEST,
    TeamProtocolType.PLAN_APPROVAL: TeamMessageType.PLAN_APPROVAL_REQUEST,
}
_PROTOCOL_RESPONSE_MESSAGE_TYPES = {
    TeamProtocolType.SHUTDOWN: TeamMessageType.SHUTDOWN_RESPONSE,
    TeamProtocolType.PLAN_APPROVAL: TeamMessageType.PLAN_APPROVAL_RESPONSE,
}
_PROTOCOL_REQUEST_TYPES = frozenset(_PROTOCOL_REQUEST_MESSAGE_TYPES.values())
_PROTOCOL_RESPONSE_TYPES = frozenset(_PROTOCOL_RESPONSE_MESSAGE_TYPES.values())


def is_protocol_request_message_type(message_type: TeamMessageType) -> bool:
    """判断消息是否为当前已知协议的 request。"""

    return message_type in _PROTOCOL_REQUEST_TYPES


def is_protocol_response_message_type(message_type: TeamMessageType) -> bool:
    """判断消息是否为当前已知协议的 response。"""

    return message_type in _PROTOCOL_RESPONSE_TYPES


def protocol_request_message_type(protocol_type: TeamProtocolType) -> TeamMessageType:
    """返回协议唯一合法的 request 消息类型。"""

    return _PROTOCOL_REQUEST_MESSAGE_TYPES[protocol_type]


def protocol_response_message_type(protocol_type: TeamProtocolType) -> TeamMessageType:
    """返回协议唯一合法的 response 消息类型。"""

    return _PROTOCOL_RESPONSE_MESSAGE_TYPES[protocol_type]
