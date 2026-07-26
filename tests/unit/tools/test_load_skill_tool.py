from __future__ import annotations

import pytest

from local_dev_agent.skills import SkillCatalog, SkillDocument, SkillMetadata
from local_dev_agent.tools import ToolCallRequest, ToolExecutionContext, ToolExecutor, ToolRegistry
from local_dev_agent.tools.builtin import LoadSkillTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


def _catalog() -> SkillCatalog:
    return SkillCatalog(
        documents=(
            SkillDocument(
                metadata=SkillMetadata(
                    name="code-review",
                    description="审查代码中的缺陷。",
                ),
                source_directory="skills/code-review",
                content="---\nname: code-review\n---\n# Code Review\n",
            ),
        )
    )


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        call_id="toolu-1",
    )


def test_load_skill_tool_returns_the_complete_snapshot_and_source_directory() -> None:
    tool = LoadSkillTool(_catalog())

    result = tool.run({"name": "code-review"}, context=_context())

    assert result == {
        "name": "code-review",
        "description": "审查代码中的缺陷。",
        "source_directory": "skills/code-review",
        "content": "---\nname: code-review\n---\n# Code Review\n",
    }
    assert tool.definition.tags == ("knowledge", "read_only")
    assert tool.definition.parameters["required"] == ["name"]


@pytest.mark.parametrize(
    ("arguments", "error_type", "message"),
    [
        ({}, ToolValidationError, "字段“name”必须是非空字符串"),
        ({"name": " "}, ToolValidationError, "字段“name”必须是非空字符串"),
        ({"name": "../code-review"}, ToolExecutionError, "找不到可加载的技能"),
    ],
)
def test_load_skill_tool_rejects_invalid_or_unknown_names(
    arguments: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        LoadSkillTool(_catalog()).run(arguments, context=_context())


def test_load_skill_tool_uses_existing_executor_validation_and_structured_failure() -> None:
    registry = ToolRegistry()
    registry.register(LoadSkillTool(_catalog()))
    result = ToolExecutor(registry).execute(
        ToolCallRequest(
            name="load_skill",
            arguments={"name": ["code-review"]},
            call_id="toolu-1",
        ),
        context=_context(),
    )

    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ToolValidationError"


def test_load_skill_tool_requires_a_catalog() -> None:
    with pytest.raises(TypeError, match="技能目录必须是 SkillCatalog 对象"):
        LoadSkillTool(object())  # type: ignore[arg-type]
