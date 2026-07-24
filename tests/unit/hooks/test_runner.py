import pytest

from local_dev_agent.hooks import (
    HookEvent,
    HookExecutionError,
    HookRegistry,
    HookResult,
    HookRunner,
    HookValidationError,
    PreToolUseContext,
    UserPromptSubmitContext,
)
from local_dev_agent.tools import ToolCallRequest


class RecordingHook:
    """记录调用上下文并返回预设结果的测试 Hook。"""

    def __init__(self, name: str, result: HookResult, calls: list[str]) -> None:
        self.name = name
        self._result = result
        self._calls = calls

    def handle(self, context: PreToolUseContext) -> HookResult:
        self._calls.append(f"{self.name}:{context.request.name}")
        return self._result


class InvalidResultHook:
    """返回非法结果，用于验证执行边界。"""

    name = "invalid-result"

    def handle(self, context: PreToolUseContext) -> object:
        return object()


class FailingHook:
    """抛出异常，用于验证异常收束。"""

    name = "failing"

    def handle(self, context: PreToolUseContext) -> HookResult:
        raise RuntimeError("测试异常")


def _pre_context() -> PreToolUseContext:
    return PreToolUseContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        request=ToolCallRequest(name="read_file", arguments={"path": "README.md"}),
    )


def test_runner_returns_continue_when_no_hook_is_registered() -> None:
    result = HookRunner(HookRegistry()).trigger(HookEvent.PRE_TOOL_USE, _pre_context())

    assert result == HookResult.continue_()


def test_runner_triggers_hooks_in_registration_order() -> None:
    calls: list[str] = []
    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        RecordingHook("first", HookResult.continue_(), calls),
    )
    registry.register(
        HookEvent.PRE_TOOL_USE,
        RecordingHook("second", HookResult.continue_(), calls),
    )

    result = HookRunner(registry).trigger(HookEvent.PRE_TOOL_USE, _pre_context())

    assert result == HookResult.continue_()
    assert calls == ["first:read_file", "second:read_file"]


def test_runner_returns_first_block_and_stops_later_hooks() -> None:
    calls: list[str] = []
    registry = HookRegistry()
    registry.register(
        HookEvent.PRE_TOOL_USE,
        RecordingHook("audit", HookResult.continue_(), calls),
    )
    registry.register(
        HookEvent.PRE_TOOL_USE,
        RecordingHook("policy", HookResult.block("策略拒绝。"), calls),
    )
    registry.register(
        HookEvent.PRE_TOOL_USE,
        RecordingHook("after", HookResult.continue_(), calls),
    )

    result = HookRunner(registry).trigger(HookEvent.PRE_TOOL_USE, _pre_context())

    assert result == HookResult.block("策略拒绝。")
    assert calls == ["audit:read_file", "policy:read_file"]


def test_runner_rejects_a_context_for_a_different_event() -> None:
    context = UserPromptSubmitContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        prompt="读取 README。",
    )

    with pytest.raises(HookValidationError, match="PreToolUseContext"):
        HookRunner(HookRegistry()).trigger(HookEvent.PRE_TOOL_USE, context)


@pytest.mark.parametrize(
    "hook, expected_message",
    [
        (InvalidResultHook(), "未返回 HookResult"),
        (FailingHook(), "回调抛出异常"),
    ],
)
def test_runner_converts_hook_contract_and_callback_failures(
    hook: object,
    expected_message: str,
) -> None:
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL_USE, hook)  # type: ignore[arg-type]

    with pytest.raises(HookExecutionError, match=expected_message):
        HookRunner(registry).trigger(HookEvent.PRE_TOOL_USE, _pre_context())
