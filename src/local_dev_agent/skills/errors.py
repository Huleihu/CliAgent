"""技能文档解析产生的领域错误。"""


class SkillFrontmatterError(ValueError):
    """当技能文档的 YAML frontmatter 缺失或格式无效时抛出。"""
