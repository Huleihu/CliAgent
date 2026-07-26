import pytest

from local_dev_agent.skills import (
    SkillCatalog,
    SkillDocument,
    SkillMetadata,
    format_skill_catalog,
)


def _catalog() -> SkillCatalog:
    code_review = SkillDocument(
        metadata=SkillMetadata(name="code-review", description="审查代码。"),
        source_directory="skills/code-review",
        content="# 不应进入目录提示的完整正文",
    )
    pdf = SkillDocument(
        metadata=SkillMetadata(name="pdf", description="处理 PDF。"),
        source_directory="skills/pdf",
        content="# 另一份完整正文",
    )
    return SkillCatalog(documents=(code_review, pdf))


def test_format_skill_catalog_lists_only_metadata_in_stable_order() -> None:
    prompt = format_skill_catalog(_catalog())

    assert "- code-review：审查代码。" in prompt
    assert "- pdf：处理 PDF。" in prompt
    assert prompt.index("code-review") < prompt.index("pdf")
    assert "不应进入目录提示的完整正文" not in prompt
    assert "load_skill" in prompt


def test_format_skill_catalog_reports_an_empty_catalog() -> None:
    assert format_skill_catalog(SkillCatalog()) == "当前没有可用技能。"


@pytest.mark.parametrize(
    ("max_characters", "message"),
    [
        (0, "必须大于或等于 1"),
        (True, "必须是整数"),
    ],
)
def test_format_skill_catalog_rejects_invalid_budget(
    max_characters: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        format_skill_catalog(_catalog(), max_characters=max_characters)


def test_format_skill_catalog_rejects_an_over_budget_catalog() -> None:
    with pytest.raises(ValueError, match="不能超过 10 个字符"):
        format_skill_catalog(_catalog(), max_characters=10)
