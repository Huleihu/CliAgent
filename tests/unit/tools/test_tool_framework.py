from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.hooks import (
    HookEvent,
    HookRegistry,
    HookResult,
    HookRunner,
    PostToolUseContext,
    PreToolUseContext,
)
from local_dev_agent.tools import (
    FakeTool,
    FunctionTool,
    ToolCallRequest,
    ToolDefinition,
    ToolDiscovery,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)
from local_dev_agent.tools.errors import (
    ToolAlreadyExistsError,
    ToolDiscoveryError,
    ToolValidationError,
)


def _read_definition() -> ToolDefinition:
    return ToolDefinition(
        name="read_file",
        description="读取文件内容。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        tags=("filesystem",),
    )


def test_executor_returns_a_success_result_and_preserves_call_id() -> None:
    tool = FakeTool(definition=_read_definition(), result={"content": "测试内容"})
    registry = ToolRegistry()
    registry.register(tool)

    result = ToolExecutor(registry).execute(
        ToolCallRequest(
            name="read_file",
            arguments={"path": "README.md"},
            call_id="toolu-1",
        )
    )

    assert result.success is True
    assert result.data == {"content": "测试内容"}
    assert result.call_id == "toolu-1"
    assert tool.calls == [{"path": "README.md"}]
    assert tool.contexts == [None]


def test_execution_context_is_immutable_and_validates_association_fields() -> None:
    context = ToolExecutionContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        call_id="toolu-1",
    )

    assert context.call_id == "toolu-1"
    with pytest.raises(FrozenInstanceError):
        context.step_id = "其他步骤"  # type: ignore[misc]

    for field_name in ("session_id", "run_id", "step_id", "call_id"):
        values = {
            "session_id": "session-1",
            "run_id": "run-1",
            "step_id": "step-1",
            "call_id": "toolu-1",
        }
        values[field_name] = " "
        with pytest.raises(
            ToolValidationError,
            match=f"字段“{field_name}”必须是非空字符串",
        ):
            ToolExecutionContext(**values)


def test_executor_converts_expected_failures_to_structured_results() -> None:
    registry = ToolRegistry()
    registry.register(
        FakeTool(definition=_read_definition(), result={"content": "测试内容"})
    )
    executor = ToolExecutor(registry)

    missing_argument = executor.execute(ToolCallRequest(name="read_file", arguments={}))
    unknown_tool = executor.execute(ToolCallRequest(name="missing", arguments={}))

    assert missing_argument.success is False
    assert missing_argument.error["type"] == "ToolValidationError"  # type: ignore[index]
    assert "缺少必填参数" in missing_argument.error["message"]  # type: ignore[index]
    assert unknown_tool.success is False
    assert unknown_tool.error["type"] == "ToolNotFoundError"  # type: ignore[index]


def test_executor_validates_nested_json_schema_before_running_a_tool() -> None:
    tool = FakeTool(
        definition=ToolDefinition(
            name="search_files",
            description="搜索文件。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "include_hidden": {"type": "boolean"},
                    "extensions": {"type": "array", "items": {"type": "string"}},
                    "options": {
                        "type": "object",
                        "properties": {"recursive": {"type": "boolean"}},
                        "required": ["recursive"],
                    },
                },
                "required": ["query"],
            },
        ),
        result={"matches": []},
    )
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(registry)

    valid_result = executor.execute(
        ToolCallRequest(
            name="search_files",
            arguments={
                "query": "Agent",
                "limit": 20,
                "include_hidden": False,
                "extensions": [".py", ".md"],
                "options": {"recursive": True},
            },
        )
    )
    invalid_results = (
        executor.execute(
            ToolCallRequest(name="search_files", arguments={"query": 123})
        ),
        executor.execute(
            ToolCallRequest(name="search_files", arguments={"query": "Agent", "extra": True})
        ),
        executor.execute(
            ToolCallRequest(
                name="search_files",
                arguments={"query": "Agent", "extensions": [".py", 1]},
            )
        ),
        executor.execute(
            ToolCallRequest(
                name="search_files",
                arguments={"query": "Agent", "options": {}},
            )
        ),
    )

    assert valid_result.success is True
    assert all(result.success is False for result in invalid_results)
    assert all(
        result.error is not None and result.error["type"] == "ToolValidationError"
        for result in invalid_results
    )
    assert tool.calls == [
        {
            "query": "Agent",
            "limit": 20,
            "include_hidden": False,
            "extensions": [".py", ".md"],
            "options": {"recursive": True},
        }
    ]


def test_executor_converts_tool_exception_and_invalid_result_to_failures() -> None:
    registry = ToolRegistry()
    registry.register(
        FunctionTool(
            definition=ToolDefinition(
                name="explode",
                description="抛出异常的测试工具。",
                parameters={"type": "object", "properties": {}},
            ),
            function=lambda arguments: (_ for _ in ()).throw(RuntimeError("测试失败")),
        )
    )
    registry.register(
        FunctionTool(
            definition=ToolDefinition(
                name="invalid_result",
                description="返回非法结果的测试工具。",
                parameters={"type": "object", "properties": {}},
            ),
            function=lambda arguments: {"value": object()},
        )
    )
    executor = ToolExecutor(registry)

    exception_result = executor.execute(ToolCallRequest(name="explode", arguments={}))
    invalid_result = executor.execute(ToolCallRequest(name="invalid_result", arguments={}))

    assert exception_result.success is False
    assert "工具执行失败" in exception_result.error["message"]  # type: ignore[index]
    assert invalid_result.success is False
    assert invalid_result.error["type"] == "ToolValidationError"  # type: ignore[index]


def test_registry_rejects_duplicate_names_and_filters_definitions() -> None:
    registry = ToolRegistry()
    tool = FakeTool(definition=_read_definition(), result={})
    registry.register(tool)

    with pytest.raises(ToolAlreadyExistsError, match="不能重复注册"):
        registry.register(tool)

    assert registry.list_definitions(tags=("filesystem",)) == (tool.definition,)
    assert registry.list_definitions(tags=("network",)) == ()


def test_call_contract_freezes_top_level_mappings() -> None:
    arguments = {"path": "README.md"}
    request = ToolCallRequest(name="read_file", arguments=arguments)
    arguments["path"] = "已修改"

    assert request.arguments["path"] == "README.md"
    with pytest.raises(TypeError):
        request.arguments["path"] = "不能修改"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        request.name = "其他工具"  # type: ignore[misc]


def test_contract_rejects_non_json_native_values() -> None:
    with pytest.raises(ToolValidationError, match="JSON 原生值"):
        ToolCallRequest(name="read_file", arguments={"path": object()})


def test_discovery_registers_direct_and_factory_tools_in_stable_order() -> None:
    registry = ToolRegistry()

    names = ToolDiscovery().register_package(
        "tests.unit.tools.discovery_samples",
        registry,
    )

    assert names == ("direct_tool", "factory_tool")
    assert [definition.name for definition in registry.list_definitions()] == [
        "direct_tool",
        "factory_tool",
    ]


def test_discovery_rejects_missing_package_and_invalid_factory() -> None:
    with pytest.raises(ToolDiscoveryError, match="无法导入工具包"):
        ToolDiscovery().register_package("not_a_package", ToolRegistry())

    with pytest.raises(ToolDiscoveryError, match="必须返回 Tool 对象"):
        ToolDiscovery().register_package(
            "tests.unit.tools.invalid_discovery_samples",
            ToolRegistry(),
        )

    with pytest.raises(ToolDiscoveryError, match="无法导入工具模块"):
        ToolDiscovery().register_package(
            "tests.unit.tools.import_failure_samples",
            ToolRegistry(),
        )


class BlockingPreToolHook:
    """用于验证执行前短路的确定性测试 Hook。"""

    name = "block-read"

    def __init__(self) -> None:
        self.contexts: list[PreToolUseContext] = []

    def handle(self, context: PreToolUseContext) -> HookResult:
        self.contexts.append(context)
        return HookResult.block("测试策略拒绝。")


def test_executor_runs_pre_tool_hook_after_validation_and_skips_blocked_tool() -> None:
    tool = FakeTool(definition=_read_definition(), result={"content": "测试内容"})
    tool_registry = ToolRegistry()
    tool_registry.register(tool)
    hook = BlockingPreToolHook()
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.PRE_TOOL_USE, hook)
    executor = ToolExecutor(tool_registry, hook_runner=HookRunner(hook_registry))
    request = ToolCallRequest(
        name="read_file",
        arguments={"path": "README.md"},
        call_id="toolu-1",
    )

    invalid_result = executor.execute(ToolCallRequest(name="read_file", arguments={}))
    blocked_result = executor.execute(
        request,
        context=ToolExecutionContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            call_id="toolu-1",
        ),
    )

    assert invalid_result.error["type"] == "ToolValidationError"  # type: ignore[index]
    assert blocked_result.success is False
    assert blocked_result.error["type"] == "ToolHookBlockedError"  # type: ignore[index]
    assert "测试策略拒绝" in blocked_result.error["message"]  # type: ignore[index]
    assert blocked_result.call_id == "toolu-1"
    assert tool.calls == []
    assert [context.request for context in hook.contexts] == [request]


def test_executor_rejects_missing_or_mismatched_context_when_hooks_are_enabled() -> None:
    tool = FakeTool(definition=_read_definition(), result={"content": "测试内容"})
    tool_registry = ToolRegistry()
    tool_registry.register(tool)
    executor = ToolExecutor(tool_registry, hook_runner=HookRunner(HookRegistry()))
    request = ToolCallRequest(
        name="read_file",
        arguments={"path": "README.md"},
        call_id="toolu-1",
    )

    missing_context = executor.execute(request)
    mismatched_context = executor.execute(
        request,
        context=ToolExecutionContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            call_id="toolu-other",
        ),
    )

    assert missing_context.error["type"] == "ToolExecutionError"  # type: ignore[index]
    assert "必须提供 ToolExecutionContext" in missing_context.error["message"]  # type: ignore[index]
    assert mismatched_context.error["type"] == "ToolExecutionError"  # type: ignore[index]
    assert "必须关联当前工具调用请求" in mismatched_context.error["message"]  # type: ignore[index]
    assert tool.calls == []


class RecordingPostToolHook:
    """记录工具结果但不改变执行结果的测试 Hook。"""

    name = "record-result"

    def __init__(self, result: HookResult | None = None) -> None:
        self.contexts: list[PostToolUseContext] = []
        self._result = result or HookResult.continue_()

    def handle(self, context: PostToolUseContext) -> HookResult:
        self.contexts.append(context)
        return self._result


class FailingPostToolHook:
    """抛出异常，用于验证观察型 Hook 不改变工具结果。"""

    name = "failing-post"

    def handle(self, context: PostToolUseContext) -> HookResult:
        raise RuntimeError("审计服务不可用")


def _execution_context(request: ToolCallRequest) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        call_id=request.call_id,
    )


def test_executor_triggers_post_tool_hook_with_the_final_success_result() -> None:
    tool = FakeTool(definition=_read_definition(), result={"content": "测试内容"})
    tool_registry = ToolRegistry()
    tool_registry.register(tool)
    post_hook = RecordingPostToolHook(HookResult.block("停止后续审计。"))
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.POST_TOOL_USE, post_hook)
    executor = ToolExecutor(tool_registry, hook_runner=HookRunner(hook_registry))
    request = ToolCallRequest(name="read_file", arguments={"path": "README.md"})

    context = _execution_context(request)

    result = executor.execute(request, context=context)

    assert result.success is True
    assert result.data == {"content": "测试内容"}
    assert tool.calls == [{"path": "README.md"}]
    assert tool.contexts == [context]
    assert post_hook.contexts[0].request is request
    assert post_hook.contexts[0].result == result


def test_executor_triggers_post_hook_for_tool_failures_but_not_pre_hook_blocks() -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
        FunctionTool(
            definition=ToolDefinition(
                name="explode",
                description="抛出异常的测试工具。",
                parameters={"type": "object", "properties": {}},
            ),
            function=lambda arguments: (_ for _ in ()).throw(RuntimeError("测试失败")),
        )
    )
    post_hook = RecordingPostToolHook()
    pre_hook = BlockingPreToolHook()
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.POST_TOOL_USE, post_hook)
    executor = ToolExecutor(tool_registry, hook_runner=HookRunner(hook_registry))
    failed_request = ToolCallRequest(name="explode", arguments={})

    failed_result = executor.execute(
        failed_request,
        context=_execution_context(failed_request),
    )

    blocking_registry = HookRegistry()
    blocking_registry.register(HookEvent.PRE_TOOL_USE, pre_hook)
    blocking_registry.register(HookEvent.POST_TOOL_USE, post_hook)
    blocked_executor = ToolExecutor(
        tool_registry,
        hook_runner=HookRunner(blocking_registry),
    )
    blocked_request = ToolCallRequest(name="explode", arguments={})
    blocked_result = blocked_executor.execute(
        blocked_request,
        context=_execution_context(blocked_request),
    )

    assert failed_result.success is False
    assert post_hook.contexts[0].result == failed_result
    assert blocked_result.error["type"] == "ToolHookBlockedError"  # type: ignore[index]
    assert len(post_hook.contexts) == 1


def test_executor_keeps_the_tool_result_when_a_post_hook_fails() -> None:
    tool = FakeTool(definition=_read_definition(), result={"content": "测试内容"})
    tool_registry = ToolRegistry()
    tool_registry.register(tool)
    hook_registry = HookRegistry()
    hook_registry.register(HookEvent.POST_TOOL_USE, FailingPostToolHook())
    executor = ToolExecutor(tool_registry, hook_runner=HookRunner(hook_registry))
    request = ToolCallRequest(name="read_file", arguments={"path": "README.md"})

    result = executor.execute(request, context=_execution_context(request))

    assert result.success is True
    assert result.data == {"content": "测试内容"}
