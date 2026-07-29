from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.system_prompt import (
    CachedSystemPromptAssembler,
    SystemPromptContext,
    SystemPromptSection,
)


def test_context_normalizes_tool_names_and_keeps_them_immutable() -> None:
    context = SystemPromptContext.create(
        workspace=" C:/workspace ",
        enabled_tool_names=[" write_file ", "read_file"],
    )

    assert context.workspace == " C:/workspace "
    assert context.enabled_tool_names == ("read_file", "write_file")
    assert context.has_tool("write_file")
    assert not context.has_tool("task")
    with pytest.raises(FrozenInstanceError):
        context.workspace = "C:/other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"workspace": "", "enabled_tool_names": ()}, "字段“workspace”必须是非空字符串"),
        (
            {"workspace": "C:/workspace", "enabled_tool_names": ["read_file"]},
            "字段“enabled_tool_names”必须是字符串元组",
        ),
        (
            {"workspace": "C:/workspace", "enabled_tool_names": ("",)},
            "字段“enabled_tool_names”必须是非空字符串元组",
        ),
        (
            {"workspace": "C:/workspace", "enabled_tool_names": ("read_file", "read_file")},
            "字段“enabled_tool_names”不能包含重复工具名称",
        ),
    ],
)
def test_context_rejects_invalid_values(arguments, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SystemPromptContext(**arguments)


def test_section_assembly_preserves_order_and_skips_unavailable_capabilities() -> None:
    assembler = CachedSystemPromptAssembler(
        (
            SystemPromptSection("identity", lambda _: "你是本地开发 Agent。"),
            SystemPromptSection("workspace", lambda context: f"工作区：{context.workspace}"),
            SystemPromptSection(
                "todo",
                lambda context: "复杂任务先维护待办清单。"
                if context.has_tool("todo_write")
                else None,
            ),
        )
    )

    prompt = assembler.get(
        SystemPromptContext.create(
            workspace="C:/workspace",
            enabled_tool_names=("read_file", "todo_write"),
        )
    )

    assert prompt == (
        "你是本地开发 Agent。\n\n"
        "工作区：C:/workspace\n\n"
        "复杂任务先维护待办清单。"
    )


def test_assembler_cache_uses_deterministic_context_state() -> None:
    render_count = 0

    def render_identity(_: SystemPromptContext) -> str:
        nonlocal render_count
        render_count += 1
        return "你是本地开发 Agent。"

    assembler = CachedSystemPromptAssembler((SystemPromptSection("identity", render_identity),))
    first_context = SystemPromptContext.create(
        workspace="C:/workspace",
        enabled_tool_names=("write_file", "read_file"),
    )
    equivalent_context = SystemPromptContext.create(
        workspace="C:/workspace",
        enabled_tool_names=("read_file", "write_file"),
    )

    assert assembler.get(first_context) == "你是本地开发 Agent。"
    assert assembler.get(equivalent_context) == "你是本地开发 Agent。"
    assert render_count == 1


def test_assembler_reassembles_when_context_changes() -> None:
    assembler = CachedSystemPromptAssembler(
        (SystemPromptSection("workspace", lambda context: f"工作区：{context.workspace}"),)
    )

    assert assembler.get(SystemPromptContext.create(workspace="C:/first")) == "工作区：C:/first"
    assert assembler.get(SystemPromptContext.create(workspace="C:/second")) == "工作区：C:/second"


@pytest.mark.parametrize(
    ("section", "message"),
    [
        (SystemPromptSection("identity", lambda _: ""), "必须返回非空字符串或 None"),
        (SystemPromptSection("identity", lambda _: 1), "必须返回非空字符串或 None"),
    ],
)
def test_section_rejects_invalid_rendered_content(section: SystemPromptSection, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        section.render(SystemPromptContext.create(workspace="C:/workspace"))


def test_assembler_rejects_duplicate_section_names() -> None:
    section = SystemPromptSection("identity", lambda _: "你是本地开发 Agent。")

    with pytest.raises(ValueError, match="系统提示 section 名称不能重复"):
        CachedSystemPromptAssembler((section, section))
