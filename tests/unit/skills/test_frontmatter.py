import pytest

from local_dev_agent.skills import SkillFrontmatterError, parse_skill_frontmatter


def test_parse_skill_frontmatter_reads_and_normalizes_multiline_description() -> None:
    parsed = parse_skill_frontmatter(
        "---\n"
        "name: code-review\n"
        "description: |\n"
        "  审查代码中的安全性、性能和可维护性。\n"
        "  用户要求审查或排查缺陷时使用。\n"
        "future_field: ignored\n"
        "---\n"
        "\n"
        "# Code Review\n"
    )

    assert parsed.name == "code-review"
    assert parsed.description == "审查代码中的安全性、性能和可维护性。 用户要求审查或排查缺陷时使用。"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# 没有 frontmatter", "必须以 YAML frontmatter 分隔符“---”开头"),
        ("---\nname: code-review\n", "缺少结束分隔符“---”"),
        ("---\n- code-review\n---\n", "YAML frontmatter 必须是对象"),
        ("---\nname: [\n---\n", "YAML frontmatter 无法解析"),
        ("---\ndescription: 审查代码。\n---\n", "字段“name”必须是非空字符串"),
        ("---\nname: code-review\ndescription: 12\n---\n", "字段“description”必须是非空字符串"),
    ],
)
def test_parse_skill_frontmatter_rejects_invalid_metadata(
    content: str,
    message: str,
) -> None:
    with pytest.raises(SkillFrontmatterError, match=message):
        parse_skill_frontmatter(content)


def test_parse_skill_frontmatter_rejects_non_string_content() -> None:
    with pytest.raises(TypeError, match="技能文档内容必须是字符串"):
        parse_skill_frontmatter(None)  # type: ignore[arg-type]
