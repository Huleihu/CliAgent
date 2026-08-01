"""Team 不可变快照与版本化 JSON 信封之间的编解码。"""

from __future__ import annotations

from datetime import datetime
from .schema import (
    Team,
    TeamAssignment,
    TeamAssignmentStatus,
    TeamMember,
    TeamMemberStatus,
    TeamMessage,
    TeamMessageDeliveryStatus,
    TeamMessageType,
    TeamStatus,
)

_SCHEMA_VERSION = 1


def encode_team(team: Team) -> dict[str, object]:
    """将 Team 写成带实体类型和版本的 JSON 信封。"""

    return _envelope(
        "team",
        {
            "team_id": team.team_id,
            "workspace_id": team.workspace_id,
            "lead_member_id": team.lead_member_id,
            "status": team.status.value,
            "created_at": team.created_at.isoformat(),
        },
    )


def decode_team(payload: dict[str, object]) -> Team:
    """恢复 Team，并拒绝未知版本或字段类型错误。"""

    data = _read_envelope(payload, "team")
    return Team(
        team_id=_text(data, "team_id"),
        workspace_id=_text(data, "workspace_id"),
        lead_member_id=_text(data, "lead_member_id"),
        status=TeamStatus(_text(data, "status")),
        created_at=_timestamp(data, "created_at"),
    )


def encode_member(member: TeamMember) -> dict[str, object]:
    """将成员身份写成版本化 JSON 信封。"""

    return _envelope(
        "team_member",
        {
            "member_id": member.member_id,
            "team_id": member.team_id,
            "name": member.name,
            "role": member.role,
            "session_id": member.session_id,
            "status": member.status.value,
            "created_at": member.created_at.isoformat(),
        },
    )


def decode_member(payload: dict[str, object]) -> TeamMember:
    """恢复成员身份与其独立 Session 绑定。"""

    data = _read_envelope(payload, "team_member")
    return TeamMember(
        member_id=_text(data, "member_id"),
        team_id=_text(data, "team_id"),
        name=_text(data, "name"),
        role=_text(data, "role"),
        session_id=_text(data, "session_id"),
        status=TeamMemberStatus(_text(data, "status")),
        created_at=_timestamp(data, "created_at"),
    )


def encode_assignment(assignment: TeamAssignment) -> dict[str, object]:
    """将 Team 工作分配写成版本化 JSON 信封。"""

    return _envelope(
        "team_assignment",
        {
            "assignment_id": assignment.assignment_id,
            "team_id": assignment.team_id,
            "assigned_by_member_id": assignment.assigned_by_member_id,
            "assignee_member_id": assignment.assignee_member_id,
            "prompt": assignment.prompt,
            "status": assignment.status.value,
            "created_at": assignment.created_at.isoformat(),
            "updated_at": assignment.updated_at.isoformat(),
            "project_task_id": assignment.project_task_id,
            "attempt": assignment.attempt,
            "last_run_id": assignment.last_run_id,
            "failure_reason": assignment.failure_reason,
        },
    )


def decode_assignment(payload: dict[str, object]) -> TeamAssignment:
    """恢复 Team 分配完整生命周期快照。"""

    data = _read_envelope(payload, "team_assignment")
    return TeamAssignment(
        assignment_id=_text(data, "assignment_id"),
        team_id=_text(data, "team_id"),
        assigned_by_member_id=_text(data, "assigned_by_member_id"),
        assignee_member_id=_text(data, "assignee_member_id"),
        prompt=_text(data, "prompt"),
        status=TeamAssignmentStatus(_text(data, "status")),
        created_at=_timestamp(data, "created_at"),
        updated_at=_timestamp(data, "updated_at"),
        project_task_id=_optional_text(data, "project_task_id"),
        attempt=_integer(data, "attempt"),
        last_run_id=_optional_text(data, "last_run_id"),
        failure_reason=_optional_text(data, "failure_reason"),
    )


def encode_message(message: TeamMessage) -> dict[str, object]:
    """编码单条消息，供收件箱集合信封复用。"""

    return {
        "message_id": message.message_id,
        "team_id": message.team_id,
        "sender_member_id": message.sender_member_id,
        "recipient_member_id": message.recipient_member_id,
        "sequence": message.sequence,
        "message_type": message.message_type.value,
        "content": message.content,
        "idempotency_key": message.idempotency_key,
        "created_at": message.created_at.isoformat(),
        "delivery_status": message.delivery_status.value,
        "reservation_id": message.reservation_id,
        "reserved_at": _optional_timestamp(message.reserved_at),
        "consumed_by_session_id": message.consumed_by_session_id,
        "consumed_by_run_id": message.consumed_by_run_id,
        "consumed_at": _optional_timestamp(message.consumed_at),
    }


def decode_message(data: dict[str, object]) -> TeamMessage:
    """从收件箱条目恢复单条消息。"""

    return TeamMessage(
        message_id=_text(data, "message_id"),
        team_id=_text(data, "team_id"),
        sender_member_id=_text(data, "sender_member_id"),
        recipient_member_id=_text(data, "recipient_member_id"),
        sequence=_integer(data, "sequence"),
        message_type=TeamMessageType(_text(data, "message_type")),
        content=_text(data, "content"),
        idempotency_key=_text(data, "idempotency_key"),
        created_at=_timestamp(data, "created_at"),
        delivery_status=TeamMessageDeliveryStatus(_text(data, "delivery_status")),
        reservation_id=_optional_text(data, "reservation_id"),
        reserved_at=_optional_timestamp_from_data(data, "reserved_at"),
        consumed_by_session_id=_optional_text(data, "consumed_by_session_id"),
        consumed_by_run_id=_optional_text(data, "consumed_by_run_id"),
        consumed_at=_optional_timestamp_from_data(data, "consumed_at"),
    )


def encode_inbox(*, next_sequence: int, messages: tuple[TeamMessage, ...]) -> dict[str, object]:
    """保存一个接收方收件箱的顺序游标与完整消息快照。"""

    return _envelope(
        "team_inbox",
        {"next_sequence": next_sequence, "messages": [encode_message(message) for message in messages]},
    )


def decode_inbox(payload: dict[str, object]) -> tuple[int, tuple[TeamMessage, ...]]:
    """恢复收件箱，并验证 sequence 游标不会倒退。"""

    data = _read_envelope(payload, "team_inbox")
    next_sequence = _integer(data, "next_sequence")
    raw_messages = data.get("messages")
    if not isinstance(raw_messages, list) or not all(isinstance(item, dict) for item in raw_messages):
        raise ValueError("字段“messages”必须是对象列表。")
    messages = tuple(decode_message(item) for item in raw_messages)
    sequences = tuple(message.sequence for message in messages)
    if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
        raise ValueError("收件箱消息 sequence 必须唯一且升序。")
    if next_sequence < len(messages) + 1 or (messages and next_sequence <= messages[-1].sequence):
        raise ValueError("收件箱 next_sequence 不合法。")
    return next_sequence, messages


def _envelope(entity_type: str, data: dict[str, object]) -> dict[str, object]:
    return {"entity_type": entity_type, "schema_version": _SCHEMA_VERSION, "data": data}


def _read_envelope(payload: dict[str, object], expected_type: str) -> dict[str, object]:
    if payload.get("entity_type") != expected_type:
        raise ValueError("Team JSON 实体类型不匹配。")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Team JSON 版本不受支持。")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Team JSON data 必须是对象。")
    return data


def _text(data: dict[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"字段“{field_name}”必须是字符串。")
    return value


def _optional_text(data: dict[str, object], field_name: str) -> str | None:
    value = data.get(field_name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"字段“{field_name}”必须是字符串或 None。")
    return value


def _integer(data: dict[str, object], field_name: str) -> int:
    value = data.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"字段“{field_name}”必须是整数。")
    return value


def _timestamp(data: dict[str, object], field_name: str) -> datetime:
    value = _text(data, field_name)
    return datetime.fromisoformat(value)


def _optional_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_timestamp_from_data(data: dict[str, object], field_name: str) -> datetime | None:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"字段“{field_name}”必须是 ISO 时间字符串或 None。")
    return datetime.fromisoformat(value)
