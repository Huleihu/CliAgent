"""S07 技能目录与按需加载的领域契约。"""

from .directory import FileSystemSkillCatalogLoader
from .errors import SkillCatalogLoadError, SkillFrontmatterError
from .frontmatter import parse_skill_frontmatter
from .schema import SkillCatalog, SkillDocument, SkillMetadata

__all__ = [
    "FileSystemSkillCatalogLoader",
    "SkillCatalog",
    "SkillCatalogLoadError",
    "SkillDocument",
    "SkillFrontmatterError",
    "SkillMetadata",
    "parse_skill_frontmatter",
]
