"""技能 YAML frontmatter 的受限解析。"""

from __future__ import annotations

from collections.abc import Mapping

import yaml

from .errors import SkillFrontmatterError
from .schema import SkillMetadata


def parse_skill_frontmatter(content: str) -> SkillMetadata:
    """解析完整 SKILL.md 的 YAML frontmatter，返回目录所需的最小元数据。"""

    if not isinstance(content, str):
        raise TypeError("技能文档内容必须是字符串。")

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillFrontmatterError("技能文档必须以 YAML frontmatter 分隔符“---”开头。")

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise SkillFrontmatterError("技能文档的 YAML frontmatter 缺少结束分隔符“---”。")

    raw_frontmatter = "".join(lines[1:closing_index])
    try:
        parsed = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as error:
        raise SkillFrontmatterError("技能文档的 YAML frontmatter 无法解析。") from error

    if not isinstance(parsed, Mapping):
        raise SkillFrontmatterError("技能文档的 YAML frontmatter 必须是对象。")

    try:
        metadata = SkillMetadata(
            name=parsed.get("name"),
            description=parsed.get("description"),
        )
    except ValueError as error:
        raise SkillFrontmatterError(str(error)) from error
    return metadata
