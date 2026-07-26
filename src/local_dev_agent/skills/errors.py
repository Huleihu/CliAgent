"""技能文档解析产生的领域错误。"""


class SkillFrontmatterError(ValueError):
    """当技能文档的 YAML frontmatter 缺失或格式无效时抛出。"""


class SkillCatalogLoadError(ValueError):
    """当受控技能目录无法形成完整、可信的目录快照时抛出。"""
