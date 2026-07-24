from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.hooks import (
    HookDecision,
    HookEvent,
    HookResult,
    HookValidationError,
    PostToolUseContext,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)
from local_dev_agent.models import ModelResponse
from local_dev_agent.tools import ToolCallRequest, ToolCallResult


def _tool_request() -> ToolCallRequest:
    return ToolCallRequest(
        name="read_file",
        arguments={"path": "README.md"},
        call_id="toolu-1",
    )


def _tool_result() -> ToolCallResult:
    return ToolCallResult.succeeded(
        name="read_file",
        data={"content": "测试内容"},
        duration_ms=1.5,
        call_id="toolu-1",
    )


def test_hook_events_expose_stable_lifecycle_values() -> None:
    assert [event.value for event in HookEvent] == [
        "user_prompt_submit",
        "pre_tool_use",
        "post_tool_use",
        "stop",
    ]


def test_contexts_preserve_their_associated_immutable_protocol_values() -> None:
    request = _tool_request()
    result = _tool_result()
    response = ModelResponse.text_completion("任务完成。")

    prompt_context = UserPromptSubmitContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        prompt="读取 README。",
    )
    pre_context = PreToolUseContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-2",
        request=request,
    )
    post_context = PostToolUseContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-2",
        request=request,
        result=result,
    )
    stop_context = StopContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-3",
        response=response,
    )

    assert prompt_context.prompt == "读取 README。"
    assert pre_context.request is request
    assert post_context.result is result
    assert stop_context.response is response
    with pytest.raises(FrozenInstanceError):
        pre_context.step_id = "其他步骤"  # type: ignore[misc]
    with pytest.raises(TypeError):
        pre_context.request.arguments["path"] = "不能修改"  # type: ignore[index]


@pytest.mark.parametrize("field_name", ["session_id", "run_id", "step_id"])
def test_contexts_reject_empty_association_identifiers(field_name: str) -> None:
    values = {
        "session_id": "session-1",
        "run_id": "run-1",
        "step_id": "step-1",
        "prompt": "读取 README。",
    }
    values[field_name] = " "

    with pytest.raises(HookValidationError, match=f"字段“{field_name}”必须是非空字符串"):
        UserPromptSubmitContext(**values)


def test_contexts_reject_invalid_protocol_value_types() -> None:
    with pytest.raises(HookValidationError, match="ToolCallRequest"):
        PreToolUseContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            request=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(HookValidationError, match="ToolCallResult"):
        PostToolUseContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            request=_tool_request(),
            result=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(HookValidationError, match="ModelResponse"):
        StopContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            response=object(),  # type: ignore[arg-type]
        )


def test_hook_result_factories_make_explicit_continue_and_block_decisions() -> None:
    assert HookResult.continue_() == HookResult(HookDecision.CONTINUE)
    assert HookResult.block("权限策略拒绝执行。") == HookResult(
        HookDecision.BLOCK,
        "权限策略拒绝执行。",
    )


@pytest.mark.parametrize(
    ("decision", "message", "expected_message"),
    [
        ("continue", None, "HookDecision"),
        (HookDecision.CONTINUE, "不应出现", "不能附带消息"),
        (HookDecision.BLOCK, None, "必须是非空字符串"),
        (HookDecision.BLOCK, " ", "必须是非空字符串"),
    ],
)
def test_hook_result_rejects_ambiguous_or_invalid_control_data(
    decision: object,
    message: str | None,
    expected_message: str,
) -> None:
    with pytest.raises(HookValidationError, match=expected_message):
        HookResult(decision=decision, message=message)  # type: ignore[arg-type]
