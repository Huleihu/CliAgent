from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.tools import (
    FakeTool,
    FunctionTool,
    ToolCallRequest,
    ToolDefinition,
    ToolDiscovery,
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
