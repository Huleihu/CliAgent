from pathlib import Path

import pytest

from local_dev_agent.skills import SkillCatalog, SkillDocument, SkillMetadata
from local_dev_agent.system_prompt import (
    CLI_IDENTITY_SYSTEM_PROMPT,
    CONTEXT_COMPACTION_SYSTEM_PROMPT,
    TASK_DELEGATION_SYSTEM_PROMPT,
    TODO_PLANNING_SYSTEM_PROMPT,
    create_cli_system_prompt_assembler,
    create_cli_system_prompt_context,
    create_cli_system_prompt_provider,
)
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry


def _registry(*tool_names: str) -> ToolRegistry:
    registry = ToolRegistry()
    for name in tool_names:
        registry.register(
            FakeTool(
                definition=ToolDefinition(
                    name=name,
                    description=f"测试工具 {name}。",
                    parameters={"type": "object", "properties": {}},
                ),
                result={},
            )
        )
    return registry


def _catalog() -> SkillCatalog:
    return SkillCatalog(
        documents=(
            SkillDocument(
                metadata=SkillMetadata(
                    name="code-review",
                    description="审查代码中的缺陷。",
                ),
                source_directory="skills/code-review",
                content="---\nname: code-review\n---\n# 完整技能正文\n",
            ),
        )
    )


def test_cli_context_uses_the_current_registry_snapshot_and_resolved_workspace(tmp_path) -> None:
    registry = _registry("write_file", "todo_write", "read_file")

    context = create_cli_system_prompt_context(workspace=tmp_path, registry=registry)

    assert context.workspace == str(tmp_path.resolve())
    assert context.enabled_tool_names == ("read_file", "todo_write", "write_file")


@pytest.mark.parametrize(
    ("workspace", "registry", "message"),
    [
        ("C:/workspace", _registry(), "workspace 必须是 Path 对象"),
        (Path("C:/workspace"), object(), "registry 必须是 ToolRegistry 对象"),
    ],
)
def test_cli_context_rejects_invalid_dependencies(workspace, registry, message: str) -> None:
    with pytest.raises(TypeError, match=message):
        create_cli_system_prompt_context(workspace=workspace, registry=registry)  # type: ignore[arg-type]


def test_cli_assembler_loads_only_guidance_backed_by_registered_tools(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())
    context = create_cli_system_prompt_context(
        workspace=tmp_path,
        registry=_registry("todo_write", "task", "compact", "load_skill"),
    )

    prompt = assembler.get(context)

    assert prompt is not None
    assert CLI_IDENTITY_SYSTEM_PROMPT in prompt
    assert f"当前工作区：{tmp_path.resolve()}" in prompt
    assert TODO_PLANNING_SYSTEM_PROMPT in prompt
    assert TASK_DELEGATION_SYSTEM_PROMPT in prompt
    assert CONTEXT_COMPACTION_SYSTEM_PROMPT in prompt
    assert "code-review" in prompt
    assert "审查代码中的缺陷。" in prompt
    assert "完整技能正文" not in prompt
    assert "todo_write" not in prompt
    assert "task" not in prompt
    assert "compact" not in prompt
    assert "load_skill" not in prompt


def test_cli_assembler_skips_unavailable_capability_guidance(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())
    context = create_cli_system_prompt_context(
        workspace=tmp_path,
        registry=_registry("read_file"),
    )

    prompt = assembler.get(context)

    assert prompt == f"{CLI_IDENTITY_SYSTEM_PROMPT}\n\n当前工作区：{tmp_path.resolve()}"


def test_cli_assembler_reports_an_empty_skill_catalog_only_when_loading_is_available(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(SkillCatalog())
    context = create_cli_system_prompt_context(
        workspace=tmp_path,
        registry=_registry("load_skill"),
    )

    assert "当前没有可用技能。" in assembler.get(context)  # type: ignore[operator]


def test_cli_provider_rechecks_the_parent_tool_registry_for_each_request(tmp_path) -> None:
    registry = _registry("todo_write")
    provider = create_cli_system_prompt_provider(
        workspace=tmp_path,
        registry=registry,
        skill_catalog=_catalog(),
    )

    first_prompt = provider.get_system_prompt()
    registry.register(
        FakeTool(
            definition=ToolDefinition(
                name="task",
                description="测试委派工具。",
                parameters={"type": "object", "properties": {}},
            ),
            result={},
        )
    )
    second_prompt = provider.get_system_prompt()

    assert TASK_DELEGATION_SYSTEM_PROMPT not in first_prompt  # type: ignore[operator]
    assert TASK_DELEGATION_SYSTEM_PROMPT in second_prompt  # type: ignore[operator]
    assert "task" not in second_prompt  # type: ignore[operator]
