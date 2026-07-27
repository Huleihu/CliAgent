from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.context.checkpoints import (
    HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION,
    HistorySummaryCheckpoint,
    HistorySummaryCheckpointSourceMismatchError,
    calculate_history_source_checksum,
    select_safe_history_checkpoint_boundary,
    validate_history_summary_checkpoint,
)
from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _messages() -> tuple[ModelMessage, ...]:
    return (
        ModelMessage(role=MessageRole.USER, content=(TextBlock("检查项目状态。"),)),
        ModelMessage(
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="toolu-1",
                    name="read_file",
                    input={"path": "README.md"},
                ),
            ),
        ),
        ModelMessage(
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="toolu-1",
                    content={"content": "项目说明"},
                ),
            ),
        ),
        ModelMessage(role=MessageRole.ASSISTANT, content=(TextBlock("已读取。"),)),
        ModelMessage(role=MessageRole.USER, content=(TextBlock("继续实现。"),)),
    )


def _checkpoint(
    messages: tuple[ModelMessage, ...],
    *,
    covered_message_count: int = 3,
) -> HistorySummaryCheckpoint:
    return HistorySummaryCheckpoint(
        session_id="session-1",
        covered_message_count=covered_message_count,
        source_checksum=calculate_history_source_checksum(
            session_id="session-1",
            messages=messages[:covered_message_count],
        ),
        summary="已检查项目状态并读取 README。",
    )


def test_history_summary_checkpoint_preserves_validated_metadata() -> None:
    messages = _messages()

    checkpoint = _checkpoint(messages)

    assert checkpoint.schema_version == HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION
    assert checkpoint.session_id == "session-1"
    assert checkpoint.covered_message_count == 3
    assert checkpoint.summary == "已检查项目状态并读取 README。"
    assert checkpoint.source_checksum.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        checkpoint.summary = "篡改摘要"  # type: ignore[misc]


def test_history_source_checksum_is_stable_and_binds_the_session_and_messages() -> None:
    messages = _messages()

    first = calculate_history_source_checksum(session_id="session-1", messages=messages[:3])
    second = calculate_history_source_checksum(session_id="session-1", messages=messages[:3])
    other_session = calculate_history_source_checksum(
        session_id="session-2",
        messages=messages[:3],
    )
    changed_messages = (*messages[:2], ModelMessage(
        role=MessageRole.USER,
        content=(ToolResultBlock(tool_use_id="toolu-1", content={"content": "已改变"}),),
    ))
    changed_source = calculate_history_source_checksum(
        session_id="session-1",
        messages=changed_messages,
    )

    assert first == second
    assert first != other_session
    assert first != changed_source


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("session_id", " ", "字段“session_id”必须是非空字符串"),
        ("covered_message_count", 0, "字段“covered_message_count”必须是正整数"),
        ("source_checksum", "sha256:invalid", "字段“source_checksum”必须是 SHA-256 校验和"),
        ("summary", " ", "字段“summary”必须是非空字符串"),
        ("schema_version", 2, "历史摘要检查点版本不受支持"),
    ],
)
def test_history_summary_checkpoint_rejects_invalid_metadata(
    field_name: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {
        "session_id": "session-1",
        "covered_message_count": 1,
        "source_checksum": "sha256:" + "a" * 64,
        "summary": "有效摘要。",
        "schema_version": HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION,
    }
    values[field_name] = value

    with pytest.raises(ValueError, match=message):
        HistorySummaryCheckpoint(**values)  # type: ignore[arg-type]


def test_safe_checkpoint_boundary_moves_before_a_tool_use_and_result_pair() -> None:
    messages = _messages()

    boundary = select_safe_history_checkpoint_boundary(messages, 2)

    assert boundary == 1


def test_safe_checkpoint_boundary_keeps_a_complete_tool_exchange() -> None:
    messages = _messages()

    boundary = select_safe_history_checkpoint_boundary(messages, 3)

    assert boundary == 3


def test_safe_checkpoint_boundary_uses_matching_tool_identifiers() -> None:
    messages = (
        ModelMessage(
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="toolu-1",
                    name="read_file",
                    input={"path": "README.md"},
                ),
            ),
        ),
        ModelMessage(
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="toolu-2",
                    content={"content": "不属于前一调用"},
                ),
            ),
        ),
    )

    assert select_safe_history_checkpoint_boundary(messages, 1) == 1


def test_safe_checkpoint_boundary_rejects_an_exchange_that_cannot_be_kept_intact() -> None:
    messages = (
        ModelMessage(
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="toolu-1",
                    name="read_file",
                    input={"path": "README.md"},
                ),
            ),
        ),
        ModelMessage(
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="toolu-1",
                    content={"content": "结果"},
                ),
            ),
        ),
    )

    with pytest.raises(ValueError, match="无法在不拆分工具调用与结果的前提下创建检查点"):
        select_safe_history_checkpoint_boundary(messages, 1)


def test_checkpoint_validation_accepts_an_unchanged_complete_source_prefix() -> None:
    messages = _messages()
    checkpoint = _checkpoint(messages)

    validate_history_summary_checkpoint(
        checkpoint,
        session_id="session-1",
        messages=messages,
    )


@pytest.mark.parametrize(
    ("checkpoint", "session_id", "messages", "message"),
    [
        (
            "other_session",
            "session-1",
            "original",
            "历史摘要检查点会话标识不匹配",
        ),
        (
            "oversized_coverage",
            "session-1",
            "original",
            "历史摘要检查点覆盖范围超过当前 Transcript",
        ),
        (
            "split_boundary",
            "session-1",
            "original",
            "历史摘要检查点边界拆分了工具调用与结果",
        ),
        (
            "changed_source",
            "session-1",
            "changed",
            "历史摘要检查点来源校验和不匹配",
        ),
    ],
)
def test_checkpoint_validation_rejects_untrusted_sources(
    checkpoint: str,
    session_id: str,
    messages: str,
    message: str,
) -> None:
    original_messages = _messages()
    checkpoint_values = {
        "other_session": HistorySummaryCheckpoint(
            session_id="session-2",
            covered_message_count=3,
            source_checksum=calculate_history_source_checksum(
                session_id="session-2",
                messages=original_messages[:3],
            ),
            summary="其他会话摘要。",
        ),
        "oversized_coverage": HistorySummaryCheckpoint(
            session_id="session-1",
            covered_message_count=6,
            source_checksum="sha256:" + "a" * 64,
            summary="越界覆盖摘要。",
        ),
        "split_boundary": _checkpoint(original_messages, covered_message_count=2),
        "changed_source": _checkpoint(original_messages),
    }
    changed_messages = (*original_messages[:2], ModelMessage(
        role=MessageRole.USER,
        content=(ToolResultBlock(tool_use_id="toolu-1", content={"content": "被改写"}),),
    ), *original_messages[3:])
    message_values = {
        "original": original_messages,
        "changed": changed_messages,
    }

    with pytest.raises(HistorySummaryCheckpointSourceMismatchError, match=message):
        validate_history_summary_checkpoint(
            checkpoint_values[checkpoint],
            session_id=session_id,
            messages=message_values[messages],
        )
