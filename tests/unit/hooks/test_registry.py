import pytest

from local_dev_agent.hooks import (
    HookAlreadyExistsError,
    HookEvent,
    HookRegistry,
    HookResult,
    HookValidationError,
    PreToolUseContext,
)


class RecordingHook:
    """记录触发顺序的确定性测试 Hook。"""

    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self._calls = calls

    def handle(self, context: PreToolUseContext) -> HookResult:
        self._calls.append(f"{self.name}:{context.request.name}")
        return HookResult.continue_()


def test_registry_keeps_hooks_in_registration_order_and_isolates_events() -> None:
    calls: list[str] = []
    first = RecordingHook("first", calls)
    second = RecordingHook("second", calls)
    registry = HookRegistry()

    registry.register(HookEvent.PRE_TOOL_USE, first)
    registry.register(HookEvent.PRE_TOOL_USE, second)

    assert registry.list_hooks(HookEvent.PRE_TOOL_USE) == (first, second)
    assert registry.list_hooks(HookEvent.POST_TOOL_USE) == ()
    assert registry.registered_events() == (HookEvent.PRE_TOOL_USE,)


def test_registry_rejects_duplicate_names_and_invalid_registrations() -> None:
    calls: list[str] = []
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL_USE, RecordingHook("audit", calls))

    with pytest.raises(HookAlreadyExistsError, match="不能重复注册"):
        registry.register(HookEvent.PRE_TOOL_USE, RecordingHook("audit", calls))
    with pytest.raises(HookValidationError, match="HookEvent"):
        registry.register("pre_tool_use", RecordingHook("other", calls))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="只能注册 Hook"):
        registry.register(HookEvent.PRE_TOOL_USE, object())  # type: ignore[arg-type]


def test_registry_returns_a_snapshot_instead_of_exposing_its_internal_collection() -> None:
    calls: list[str] = []
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL_USE, RecordingHook("audit", calls))

    hooks = registry.list_hooks(HookEvent.PRE_TOOL_USE)

    assert isinstance(hooks, tuple)
    with pytest.raises(AttributeError):
        hooks.append(RecordingHook("other", calls))  # type: ignore[attr-defined]
