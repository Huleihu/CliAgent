"""Session、Run 与 Step 状态快照的 JSON 编解码。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from local_dev_agent.domain.state import (
    RunState,
    RunStatus,
    RunTransition,
    SessionState,
    SessionStatus,
    SessionTransition,
    StepState,
    StepStatus,
    StepTransition,
    StepType,
)
from local_dev_agent.domain.state.timestamps import normalize_utc_timestamp


SCHEMA_VERSION = 1


def encode_session(state: SessionState) -> dict[str, object]:
    """将会话快照转换为可读、带版本的 JSON 数据。"""

    return _envelope(
        entity_type="session",
        state={
            "session_id": state.session_id,
            "tenant_id": state.tenant_id,
            "user_id": state.user_id,
            "project_id": state.project_id,
            "status": state.status.value,
            "created_at": _format_timestamp(state.created_at),
            "updated_at": _format_timestamp(state.updated_at),
            "last_active_at": _format_timestamp(state.last_active_at),
            "active_run_id": state.active_run_id,
            "state_version": state.state_version,
            "transition_history": [
                {
                    "source_status": item.source_status.value,
                    "target_status": item.target_status.value,
                    "occurred_at": _format_timestamp(item.occurred_at),
                    "reason": item.reason,
                }
                for item in state.transition_history
            ],
        },
    )


def decode_session(payload: dict[str, Any]) -> SessionState:
    """从经过结构校验的 JSON 数据恢复会话快照。"""

    state = _get_state(payload, entity_type="session")
    return SessionState(
        session_id=_get_string(state, "session_id"),
        tenant_id=_get_string(state, "tenant_id"),
        user_id=_get_string(state, "user_id"),
        project_id=_get_string(state, "project_id"),
        status=SessionStatus(_get_string(state, "status")),
        created_at=_parse_timestamp(state, "created_at", subject="会话"),
        updated_at=_parse_timestamp(state, "updated_at", subject="会话"),
        last_active_at=_parse_timestamp(state, "last_active_at", subject="会话"),
        active_run_id=_get_optional_string(state, "active_run_id"),
        state_version=_get_positive_integer(state, "state_version"),
        transition_history=tuple(
            SessionTransition(
                source_status=SessionStatus(_get_string(item, "source_status")),
                target_status=SessionStatus(_get_string(item, "target_status")),
                occurred_at=_parse_timestamp(item, "occurred_at", subject="会话"),
                reason=_get_optional_string(item, "reason"),
            )
            for item in _get_object_list(state, "transition_history")
        ),
    )


def encode_run(state: RunState) -> dict[str, object]:
    """将运行快照转换为可读、带版本的 JSON 数据。"""

    return _envelope(
        entity_type="run",
        state={
            "run_id": state.run_id,
            "session_id": state.session_id,
            "status": state.status.value,
            "created_at": _format_timestamp(state.created_at),
            "updated_at": _format_timestamp(state.updated_at),
            "state_version": state.state_version,
            "transition_history": [
                {
                    "source_status": item.source_status.value,
                    "target_status": item.target_status.value,
                    "occurred_at": _format_timestamp(item.occurred_at),
                    "reason": item.reason,
                }
                for item in state.transition_history
            ],
        },
    )


def decode_run(payload: dict[str, Any]) -> RunState:
    """从经过结构校验的 JSON 数据恢复运行快照。"""

    state = _get_state(payload, entity_type="run")
    return RunState(
        run_id=_get_string(state, "run_id"),
        session_id=_get_string(state, "session_id"),
        status=RunStatus(_get_string(state, "status")),
        created_at=_parse_timestamp(state, "created_at", subject="运行"),
        updated_at=_parse_timestamp(state, "updated_at", subject="运行"),
        state_version=_get_positive_integer(state, "state_version"),
        transition_history=tuple(
            RunTransition(
                source_status=RunStatus(_get_string(item, "source_status")),
                target_status=RunStatus(_get_string(item, "target_status")),
                occurred_at=_parse_timestamp(item, "occurred_at", subject="运行"),
                reason=_get_optional_string(item, "reason"),
            )
            for item in _get_object_list(state, "transition_history")
        ),
    )


def encode_step(state: StepState) -> dict[str, object]:
    """将步骤快照转换为可读、带版本的 JSON 数据。"""

    return _envelope(
        entity_type="step",
        state={
            "step_id": state.step_id,
            "run_id": state.run_id,
            "step_type": state.step_type.value,
            "status": state.status.value,
            "created_at": _format_timestamp(state.created_at),
            "updated_at": _format_timestamp(state.updated_at),
            "attempt": state.attempt,
            "state_version": state.state_version,
            "transition_history": [
                {
                    "source_status": item.source_status.value,
                    "target_status": item.target_status.value,
                    "occurred_at": _format_timestamp(item.occurred_at),
                    "reason": item.reason,
                }
                for item in state.transition_history
            ],
        },
    )


def decode_step(payload: dict[str, Any]) -> StepState:
    """从经过结构校验的 JSON 数据恢复步骤快照。"""

    state = _get_state(payload, entity_type="step")
    return StepState(
        step_id=_get_string(state, "step_id"),
        run_id=_get_string(state, "run_id"),
        step_type=StepType(_get_string(state, "step_type")),
        status=StepStatus(_get_string(state, "status")),
        created_at=_parse_timestamp(state, "created_at", subject="步骤"),
        updated_at=_parse_timestamp(state, "updated_at", subject="步骤"),
        attempt=_get_positive_integer(state, "attempt"),
        state_version=_get_positive_integer(state, "state_version"),
        transition_history=tuple(
            StepTransition(
                source_status=StepStatus(_get_string(item, "source_status")),
                target_status=StepStatus(_get_string(item, "target_status")),
                occurred_at=_parse_timestamp(item, "occurred_at", subject="步骤"),
                reason=_get_optional_string(item, "reason"),
            )
            for item in _get_object_list(state, "transition_history")
        ),
    )


def _envelope(*, entity_type: str, state: dict[str, object]) -> dict[str, object]:
    """为所有状态文件添加可演进的公共结构。"""

    return {
        "schema_version": SCHEMA_VERSION,
        "entity_type": entity_type,
        "state": state,
    }


def _get_state(payload: dict[str, Any], *, entity_type: str) -> dict[str, Any]:
    """验证公共结构，避免错误实体被恢复为错误状态。"""

    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("entity_type") != entity_type
        or not isinstance(payload.get("state"), dict)
    ):
        raise ValueError("状态文件结构不受支持。")
    return payload["state"]


def _get_string(payload: dict[str, Any], field_name: str) -> str:
    """读取非空字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"状态文件字段“{field_name}”必须是非空字符串。")
    return value


def _get_optional_string(payload: dict[str, Any], field_name: str) -> str | None:
    """读取允许为空的字符串字段。"""

    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"状态文件字段“{field_name}”必须是字符串或空值。")
    return value


def _get_positive_integer(payload: dict[str, Any], field_name: str) -> int:
    """读取正整数版本或尝试次数字段。"""

    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"状态文件字段“{field_name}”必须是正整数。")
    return value


def _get_object_list(payload: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    """读取由对象组成的转换历史。"""

    value = payload.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"状态文件字段“{field_name}”必须是对象列表。")
    return value


def _parse_timestamp(
    payload: dict[str, Any],
    field_name: str,
    *,
    subject: str,
) -> datetime:
    """解析并统一为 UTC，复用领域层的时间边界规则。"""

    value = _get_string(payload, field_name)
    try:
        return normalize_utc_timestamp(datetime.fromisoformat(value), subject=subject)
    except ValueError as error:
        raise ValueError(f"状态文件字段“{field_name}”不是有效的带时区时间。") from error


def _format_timestamp(timestamp: datetime) -> str:
    """生成包含 UTC 偏移量的可读时间字符串。"""

    return timestamp.isoformat()
