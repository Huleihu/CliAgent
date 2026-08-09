from pathlib import Path

import pytest

from local_dev_agent.skills import SkillCatalog, SkillDocument, SkillMetadata
from local_dev_agent.system_prompt import (
    BACKGROUND_TASK_SYSTEM_PROMPT,
    CRON_SCHEDULER_SYSTEM_PROMPT,
    CLI_IDENTITY_SYSTEM_PROMPT,
    CONTEXT_COMPACTION_SYSTEM_PROMPT,
    TASK_DELEGATION_SYSTEM_PROMPT,
    TASK_SYSTEM_PROMPT,
    TEAM_SYSTEM_PROMPT,
    WORKTREE_ISOLATION_SYSTEM_PROMPT,
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
        registry=_registry(
            "todo_write",
            "task_create",
            "task_list",
            "task_get",
            "task_claim",
            "task_complete",
            "task",
            "bash",
            "schedule_cron",
            "list_crons",
            "cancel_cron",
            "compact",
            "create_team",
            "add_teammate",
            "assign_team_work",
            "send_team_message",
            "load_skill",
        ),
    )

    prompt = assembler.get(context)

    assert prompt is not None
    assert CLI_IDENTITY_SYSTEM_PROMPT in prompt
    assert f"当前工作区：{tmp_path.resolve()}" in prompt
    assert TODO_PLANNING_SYSTEM_PROMPT in prompt
    assert TASK_SYSTEM_PROMPT in prompt
    assert TASK_DELEGATION_SYSTEM_PROMPT in prompt
    assert BACKGROUND_TASK_SYSTEM_PROMPT in prompt
    assert CRON_SCHEDULER_SYSTEM_PROMPT in prompt
    assert CONTEXT_COMPACTION_SYSTEM_PROMPT in prompt
    assert TEAM_SYSTEM_PROMPT in prompt
    assert "code-review" in prompt
    assert "审查代码中的缺陷。" in prompt
    assert "完整技能正文" not in prompt
    assert "todo_write" not in prompt
    assert "task_create" not in prompt
    assert "task_list" not in prompt
    assert "task_get" not in prompt
    assert "task_claim" not in prompt
    assert "task_complete" not in prompt
    assert "task" not in prompt
    assert "bash" not in prompt
    assert "schedule_cron" not in prompt
    assert "list_crons" not in prompt
    assert "cancel_cron" not in prompt
    assert "compact" not in prompt
    assert "load_skill" not in prompt


def test_cli_assembler_requires_all_team_tools_before_loading_guidance(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())

    incomplete_prompt = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry("create_team", "add_teammate", "assign_team_work"),
        )
    )
    complete_prompt = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry(
                "create_team",
                "add_teammate",
                "assign_team_work",
                "send_team_message",
            ),
        )
    )

    assert TEAM_SYSTEM_PROMPT not in incomplete_prompt  # type: ignore[operator]
    assert TEAM_SYSTEM_PROMPT in complete_prompt  # type: ignore[operator]
    assert "自主发现和认领" in complete_prompt  # type: ignore[operator]
    assert "显式 Team 工作分配" in complete_prompt  # type: ignore[operator]


def test_cli_assembler_requires_all_worktree_tools_before_loading_guidance(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())

    incomplete_prompt = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry("create_worktree", "keep_worktree"),
        )
    )
    complete_prompt = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry(
                "create_worktree",
                "keep_worktree",
                "remove_worktree",
            ),
        )
    )

    assert WORKTREE_ISOLATION_SYSTEM_PROMPT not in incomplete_prompt  # type: ignore[operator]
    assert WORKTREE_ISOLATION_SYSTEM_PROMPT in complete_prompt  # type: ignore[operator]
    assert "任务图决定“谁做什么”" in complete_prompt  # type: ignore[operator]


def test_cli_assembler_skips_unavailable_capability_guidance(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())
    context = create_cli_system_prompt_context(
        workspace=tmp_path,
        registry=_registry("read_file"),
    )

    prompt = assembler.get(context)

    assert prompt == f"{CLI_IDENTITY_SYSTEM_PROMPT}\n\n当前工作区：{tmp_path.resolve()}"


def test_cli_assembler_requires_all_task_system_tools_before_loading_guidance(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())
    context = create_cli_system_prompt_context(
        workspace=tmp_path,
        registry=_registry("task_create", "task_list", "task_get", "task_claim"),
    )

    prompt = assembler.get(context)

    assert TASK_SYSTEM_PROMPT not in prompt  # type: ignore[operator]


def test_cli_assembler_requires_the_parent_command_tool_for_background_guidance(
    tmp_path,
) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())

    prompt_without_capability = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry("read_file"),
        )
    )
    prompt_with_capability = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry("read_file", "bash"),
        )
    )

    assert BACKGROUND_TASK_SYSTEM_PROMPT not in prompt_without_capability  # type: ignore[operator]
    assert BACKGROUND_TASK_SYSTEM_PROMPT in prompt_with_capability  # type: ignore[operator]


def test_cli_assembler_requires_all_parent_cron_tools_before_loading_guidance(tmp_path) -> None:
    assembler = create_cli_system_prompt_assembler(_catalog())

    incomplete_prompt = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry("schedule_cron", "list_crons"),
        )
    )
    complete_prompt = assembler.get(
        create_cli_system_prompt_context(
            workspace=tmp_path,
            registry=_registry("schedule_cron", "list_crons", "cancel_cron"),
        )
    )

    assert CRON_SCHEDULER_SYSTEM_PROMPT not in incomplete_prompt  # type: ignore[operator]
    assert CRON_SCHEDULER_SYSTEM_PROMPT in complete_prompt  # type: ignore[operator]


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
