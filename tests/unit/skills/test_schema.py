from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.skills import SkillCatalog, SkillDocument, SkillMetadata


def test_skill_metadata_normalizes_catalog_display_text() -> None:
    metadata = SkillMetadata(
        name="  code-review  ",
        description="执行全面的\n  代码审查。 ",
    )

    assert metadata.name == "code-review"
    assert metadata.description == "执行全面的 代码审查。"


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("name", " ", "字段“name”必须是非空字符串"),
        ("description", "", "字段“description”必须是非空字符串"),
    ],
)
def test_skill_metadata_rejects_blank_text(
    field_name: str,
    value: str,
    message: str,
) -> None:
    arguments = {"name": "code-review", "description": "审查代码。"}
    arguments[field_name] = value

    with pytest.raises(ValueError, match=message):
        SkillMetadata(**arguments)


def test_skill_document_requires_metadata_and_preserves_raw_content() -> None:
    metadata = SkillMetadata(name="code-review", description="审查代码。")
    content = "---\nname: code-review\ndescription: 审查代码。\n---\n\n# 正文\n"

    document = SkillDocument(metadata=metadata, content=content)

    assert document.content == content
    with pytest.raises(ValueError, match="字段“metadata”必须是 SkillMetadata 对象"):
        SkillDocument(metadata="code-review", content=content)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="字段“content”必须是非空字符串"):
        SkillDocument(metadata=metadata, content=" ")


def test_skill_models_cannot_be_mutated_directly() -> None:
    metadata = SkillMetadata(name="code-review", description="审查代码。")
    document = SkillDocument(metadata=metadata, content="# 正文")

    with pytest.raises(FrozenInstanceError):
        metadata.name = "pdf"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        document.content = "# 新正文"  # type: ignore[misc]


def test_skill_catalog_exposes_metadata_and_uses_exact_name_lookup() -> None:
    code_review = SkillDocument(
        metadata=SkillMetadata(name="code-review", description="审查代码。"),
        content="# Code Review",
    )
    pdf = SkillDocument(
        metadata=SkillMetadata(name="pdf", description="处理 PDF。"),
        content="# PDF",
    )
    catalog = SkillCatalog(documents=(code_review, pdf))

    assert catalog.metadata == (code_review.metadata, pdf.metadata)
    assert catalog.get_document("code-review") is code_review
    assert catalog.get_document("unknown") is None
    with pytest.raises(ValueError, match="字段“name”必须是非空字符串"):
        catalog.get_document(" ")


def test_skill_catalog_rejects_unstable_or_duplicate_documents() -> None:
    code_review = SkillDocument(
        metadata=SkillMetadata(name="code-review", description="审查代码。"),
        content="# Code Review",
    )
    pdf = SkillDocument(
        metadata=SkillMetadata(name="pdf", description="处理 PDF。"),
        content="# PDF",
    )

    with pytest.raises(ValueError, match="必须按技能名称升序排列"):
        SkillCatalog(documents=(pdf, code_review))
    with pytest.raises(ValueError, match="不能包含重复名称"):
        SkillCatalog(documents=(code_review, code_review))
