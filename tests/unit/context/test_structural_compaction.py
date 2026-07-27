from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.context import (
    ContextInputSnapshot,
    ConversationSnipCompactor,
    ToolResultMicroCompactor,
)
from local_dev_agent.models import (
    MessageRole,
    ModelMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _text_message(role: MessageRole, text: str) -> ModelMessage:
    return ModelMessage(role=role, content=(TextBlock(text),))


def _tool_call(tool_use_id: str) -> ModelMessage:
    return ModelMessage(
        role=MessageRole.ASSISTANT,
        content=(
            ToolUseBlock(
                tool_use_id=tool_use_id,
                name="read_file",
                input={"path": "README.md"},
            ),
        ),
    )


def _tool_result(tool_use_id: str, content: str, *, is_error: bool = False) -> ModelMessage:
    return ModelMessage(
        role=MessageRole.USER,
        content=(
            ToolResultBlock(
                tool_use_id=tool_use_id,
                content={"content": content},
                is_error=is_error,
            ),
        ),
    )


def _snapshot(*messages: ModelMessage) -> ContextInputSnapshot:
    return ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=messages,
    )


def test_snip_compactor_returns_original_snapshot_within_message_limit() -> None:
    snapshot = _snapshot(
        _text_message(MessageRole.USER, "第一条。"),
        _text_message(MessageRole.ASSISTANT, "第二条。"),
    )

    result = ConversationSnipCompactor(
        max_message_count=3,
        keep_head_message_count=1,
    ).compact(snapshot)

    assert result is snapshot


def test_snip_compactor_replaces_the_middle_with_a_message_placeholder() -> None:
    messages = tuple(
        _text_message(
            MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
            f"消息 {index}",
        )
        for index in range(8)
    )
    snapshot = _snapshot(*messages)

    result = ConversationSnipCompactor(
        max_message_count=5,
        keep_head_message_count=2,
    ).compact(snapshot)

    assert result is not snapshot
    assert result.messages[:2] == messages[:2]
    assert result.messages[-3:] == messages[-3:]
    placeholder = result.messages[2]
    assert placeholder.role is MessageRole.USER
    assert placeholder.content == (TextBlock("[已裁剪中间的 3 条历史消息。]"),)
    assert snapshot.messages == messages


def test_snip_compactor_keeps_a_head_tool_call_with_its_following_result() -> None:
    messages = (
        _text_message(MessageRole.USER, "目标。"),
        _tool_call("toolu-head"),
        _tool_result("toolu-head", "头部工具结果。"),
        _text_message(MessageRole.ASSISTANT, "旧消息 1。"),
        _text_message(MessageRole.USER, "旧消息 2。"),
        _text_message(MessageRole.ASSISTANT, "旧消息 3。"),
        _tool_call("toolu-tail"),
        _tool_result("toolu-tail", "尾部工具结果。"),
        _text_message(MessageRole.ASSISTANT, "当前结论。"),
    )

    result = ConversationSnipCompactor(
        max_message_count=5,
        keep_head_message_count=2,
    ).compact(_snapshot(*messages))

    assert result.messages[:3] == messages[:3]
    assert result.messages[-3:] == messages[-3:]
    assert result.messages[3].content == (TextBlock("[已裁剪中间的 3 条历史消息。]"),)


def test_snip_compactor_keeps_a_tail_tool_result_with_its_triggering_call() -> None:
    messages = (
        _text_message(MessageRole.USER, "目标。"),
        _text_message(MessageRole.ASSISTANT, "早期结论。"),
        _text_message(MessageRole.USER, "旧消息 1。"),
        _text_message(MessageRole.ASSISTANT, "旧消息 2。"),
        _text_message(MessageRole.USER, "旧消息 3。"),
        _tool_call("toolu-tail"),
        _tool_result("toolu-tail", "尾部工具结果。"),
        _text_message(MessageRole.ASSISTANT, "当前结论。"),
        _text_message(MessageRole.USER, "继续。"),
    )

    result = ConversationSnipCompactor(
        max_message_count=5,
        keep_head_message_count=2,
    ).compact(_snapshot(*messages))

    assert result.messages[:2] == messages[:2]
    assert result.messages[-4:] == messages[5:]
    assert result.messages[2].content == (TextBlock("[已裁剪中间的 3 条历史消息。]"),)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"max_message_count": 0}, "字段“max_message_count”必须是正整数"),
        (
            {"max_message_count": 3, "keep_head_message_count": 3},
            "keep_head_message_count 必须小于 max_message_count",
        ),
        (
            {"keep_head_message_count": False},
            "字段“keep_head_message_count”必须是正整数",
        ),
    ],
)
def test_snip_compactor_rejects_invalid_configuration(
    arguments: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ConversationSnipCompactor(**arguments)


def test_micro_compactor_replaces_old_results_and_preserves_recent_results() -> None:
    old_success = _tool_result("toolu-old-success", "甲" * 100)
    old_error = _tool_result("toolu-old-error", "乙" * 100, is_error=True)
    recent = _tool_result("toolu-recent", "丙" * 100)
    snapshot = _snapshot(old_success, old_error, recent)

    result = ToolResultMicroCompactor(
        keep_recent_result_count=1,
        minimum_result_bytes=20,
    ).compact(snapshot)

    assert result is not snapshot
    old_success_block = result.messages[0].content[0]
    old_error_block = result.messages[1].content[0]
    assert isinstance(old_success_block, ToolResultBlock)
    assert isinstance(old_error_block, ToolResultBlock)
    assert old_success_block.tool_use_id == "toolu-old-success"
    assert not old_success_block.is_error
    assert old_error_block.tool_use_id == "toolu-old-error"
    assert old_error_block.is_error
    assert old_success_block.content == {
        "notice": "较早工具结果已压缩；如需完整内容，请重新执行该工具调用。"
    }
    assert old_error_block.content == old_success_block.content
    assert result.messages[2] == recent
    assert snapshot.messages == (old_success, old_error, recent)


def test_micro_compactor_keeps_small_old_results_and_recent_large_results() -> None:
    old_small = _tool_result("toolu-old", "短")
    recent_large = _tool_result("toolu-recent", "甲" * 100)
    snapshot = _snapshot(old_small, recent_large)

    result = ToolResultMicroCompactor(
        keep_recent_result_count=1,
        minimum_result_bytes=100,
    ).compact(snapshot)

    assert result is snapshot


def test_micro_compactor_returns_original_snapshot_when_result_count_is_within_limit() -> None:
    snapshot = _snapshot(
        _tool_result("toolu-1", "甲" * 100),
        _tool_result("toolu-2", "乙" * 100),
    )

    result = ToolResultMicroCompactor(
        keep_recent_result_count=2,
        minimum_result_bytes=20,
    ).compact(snapshot)

    assert result is snapshot


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"keep_recent_result_count": -1},
            "字段“keep_recent_result_count”必须是非负整数",
        ),
        (
            {"minimum_result_bytes": 0},
            "字段“minimum_result_bytes”必须是正整数",
        ),
    ],
)
def test_micro_compactor_rejects_invalid_configuration(
    arguments: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ToolResultMicroCompactor(**arguments)


def test_compactors_do_not_mutate_the_input_snapshot() -> None:
    snapshot = _snapshot(
        _tool_result("toolu-old", "甲" * 100),
        _tool_result("toolu-recent", "乙" * 100),
        _text_message(MessageRole.ASSISTANT, "当前结论。"),
        _text_message(MessageRole.USER, "继续。"),
        _text_message(MessageRole.ASSISTANT, "下一步。"),
        _text_message(MessageRole.USER, "确认。"),
    )

    snipped = ConversationSnipCompactor(
        max_message_count=4,
        keep_head_message_count=1,
    ).compact(snapshot)
    micro_compacted = ToolResultMicroCompactor(
        keep_recent_result_count=1,
        minimum_result_bytes=20,
    ).compact(snapshot)

    assert snapshot.messages[0].content[0].content == {"content": "甲" * 100}  # type: ignore[union-attr]
    assert snipped is not snapshot
    assert micro_compacted is not snapshot
    with pytest.raises(FrozenInstanceError):
        snapshot.messages = ()  # type: ignore[misc]
