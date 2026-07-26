from pathlib import Path

import pytest

from local_dev_agent.skills import FileSystemSkillCatalogLoader, SkillCatalogLoadError


def _write_skill(
    workspace: Path,
    directory_name: str,
    *,
    name: str,
    description: str = "用于测试。",
    body: str = "# 正文\n",
) -> Path:
    manifest = workspace / "skills" / directory_name / "SKILL.md"
    manifest.parent.mkdir(parents=True)
    description_field = (
        "description: |\n" + "\n".join(f"  {line}" for line in description.splitlines())
        if "\n" in description
        else f"description: {description}"
    )
    manifest.write_text(
        f"---\nname: {name}\n{description_field}\n---\n\n{body}",
        encoding="utf-8",
    )
    return manifest


def test_loader_returns_an_empty_catalog_when_skills_directory_is_missing(
    tmp_path: Path,
) -> None:
    catalog = FileSystemSkillCatalogLoader(tmp_path).load()

    assert catalog.documents == ()
    assert catalog.metadata == ()


def test_loader_creates_a_sorted_snapshot_from_direct_skill_directories(
    tmp_path: Path,
) -> None:
    code_review = _write_skill(
        tmp_path,
        "z-review",
        name="code-review",
        description="审查\n代码。",
    )
    _write_skill(tmp_path, "a-pdf", name="pdf")
    (tmp_path / "skills" / "no-manifest").mkdir()
    (tmp_path / "skills" / "ignored.txt").write_text("忽略", encoding="utf-8")

    catalog = FileSystemSkillCatalogLoader(tmp_path).load()

    assert [metadata.name for metadata in catalog.metadata] == ["code-review", "pdf"]
    assert catalog.get_document("code-review").content == code_review.read_bytes().decode(
        "utf-8"
    )
    assert catalog.get_document("code-review").source_directory == "skills/z-review"
    assert catalog.get_document("code-review").metadata.description == "审查 代码。"


def test_loader_rejects_duplicate_skill_names(tmp_path: Path) -> None:
    _write_skill(tmp_path, "review-a", name="code-review")
    _write_skill(tmp_path, "review-b", name="code-review")

    with pytest.raises(SkillCatalogLoadError, match="技能目录包含重复名称：code-review"):
        FileSystemSkillCatalogLoader(tmp_path).load()


def test_loader_rejects_invalid_manifest_encoding_and_frontmatter(tmp_path: Path) -> None:
    invalid_encoding = tmp_path / "skills" / "binary" / "SKILL.md"
    invalid_encoding.parent.mkdir(parents=True)
    invalid_encoding.write_bytes(b"\xff\xfe")

    with pytest.raises(SkillCatalogLoadError, match="不是 UTF-8 文本"):
        FileSystemSkillCatalogLoader(tmp_path).load()

    invalid_encoding.write_text("# 没有 frontmatter", encoding="utf-8")
    with pytest.raises(SkillCatalogLoadError, match="格式无效"):
        FileSystemSkillCatalogLoader(tmp_path).load()


def test_loader_enforces_document_count_and_size_budgets(tmp_path: Path) -> None:
    _write_skill(tmp_path, "one", name="one")
    _write_skill(tmp_path, "two", name="two")

    with pytest.raises(SkillCatalogLoadError, match="文档数量不能超过 1"):
        FileSystemSkillCatalogLoader(tmp_path, max_documents=1).load()
    with pytest.raises(SkillCatalogLoadError, match="不能超过 10 字节"):
        FileSystemSkillCatalogLoader(tmp_path, max_document_bytes=10).load()


@pytest.mark.parametrize(
    ("directory_name", "message"),
    [
        ("", "字段“directory_name”必须是非空字符串"),
        ("../skills", "必须是单层相对目录名称"),
        ("nested/skills", "必须是单层相对目录名称"),
    ],
)
def test_loader_rejects_an_unsafe_skills_directory_name(
    tmp_path: Path,
    directory_name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        FileSystemSkillCatalogLoader(tmp_path, directory_name=directory_name)


def test_loader_rejects_a_skills_path_that_is_not_a_directory(tmp_path: Path) -> None:
    (tmp_path / "skills").write_text("不是目录", encoding="utf-8")

    with pytest.raises(SkillCatalogLoadError, match="技能目录不是目录"):
        FileSystemSkillCatalogLoader(tmp_path).load()
