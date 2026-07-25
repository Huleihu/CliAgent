from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.subagents import (
    DEFAULT_SUBAGENT_TOOL_NAMES,
    SUBAGENT_SYSTEM_PROMPT,
    SubagentPolicy,
    SubagentToolRegistryFactory,
)
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry
from local_dev_agent.tools.errors import ToolNotFoundError


def _tool(name: str) -> FakeTool:
    return FakeTool(
        definition=ToolDefinition(
            name=name,
            description=f"测试工具：{name}。",
            parameters={"type": "object", "properties": {}},
        ),
        result={"tool": name},
    )


def _parent_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in (*DEFAULT_SUBAGENT_TOOL_NAMES, "todo_write", "task"):
        registry.register(_tool(name))
    return registry


def test_default_policy_exposes_a_bounded_file_tool_allowlist() -> None:
    policy = SubagentPolicy()

    assert policy.max_turns == 10
    assert policy.allowed_tool_names == DEFAULT_SUBAGENT_TOOL_NAMES
    assert policy.system_prompt == SUBAGENT_SYSTEM_PROMPT


def test_policy_create_copies_tool_names_and_is_immutable() -> None:
    names = ["read_file"]

    policy = SubagentPolicy.create(max_turns=3, allowed_tool_names=names)
    names.append("write_file")

    assert policy.allowed_tool_names == ("read_file",)
    with pytest.raises(FrozenInstanceError):
        policy.max_turns = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    ("max_turns", "message"),
    [
        (True, "必须是整数"),
        ("10", "必须是整数"),
        (0, "必须大于或等于 1"),
    ],
)
def test_policy_rejects_invalid_turn_budgets(max_turns: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SubagentPolicy(max_turns=max_turns)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tool_names", "message"),
    [
        (["read_file"], "必须是非空字符串元组"),
        (("read_file", ""), "必须是非空字符串元组"),
        (("read_file", "read_file"), "不能包含重复工具名称"),
        (("task",), "不允许使用工具：task"),
        (("todo_write",), "不允许使用工具：todo_write"),
    ],
)
def test_policy_rejects_invalid_or_forbidden_tool_names(
    tool_names: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SubagentPolicy(allowed_tool_names=tool_names)  # type: ignore[arg-type]


@pytest.mark.parametrize("prompt", ["", "   "])
def test_policy_rejects_a_blank_subagent_system_prompt(prompt: str) -> None:
    with pytest.raises(ValueError, match="字段“system_prompt”必须是非空字符串"):
        SubagentPolicy(system_prompt=prompt)


def test_factory_creates_a_new_restricted_registry_without_changing_parent() -> None:
    parent_registry = _parent_registry()
    policy = SubagentPolicy.create(
        max_turns=3,
        allowed_tool_names=("read_file", "write_file"),
    )

    child_registry = SubagentToolRegistryFactory(parent_registry, policy).create()

    assert child_registry is not parent_registry
    assert [definition.name for definition in child_registry.list_definitions()] == [
        "read_file",
        "write_file",
    ]
    assert child_registry.get("read_file") is parent_registry.get("read_file")
    assert [definition.name for definition in parent_registry.list_definitions()] == sorted(
        (*DEFAULT_SUBAGENT_TOOL_NAMES, "todo_write", "task")
    )
    with pytest.raises(ToolNotFoundError, match="todo_write"):
        child_registry.get("todo_write")
    with pytest.raises(ToolNotFoundError, match="task"):
        child_registry.get("task")


def test_factory_rejects_invalid_dependencies_and_missing_allowed_tools() -> None:
    policy = SubagentPolicy.create(allowed_tool_names=("read_file",))

    with pytest.raises(TypeError, match="父工具目录必须是 ToolRegistry 对象"):
        SubagentToolRegistryFactory(object(), policy)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="子 Agent 策略必须是 SubagentPolicy 对象"):
        SubagentToolRegistryFactory(ToolRegistry(), object())  # type: ignore[arg-type]
    with pytest.raises(ToolNotFoundError, match="read_file"):
        SubagentToolRegistryFactory(ToolRegistry(), policy).create()
