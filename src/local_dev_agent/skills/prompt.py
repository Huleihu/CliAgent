"""技能目录的最小系统提示格式化。"""

from __future__ import annotations

from .schema import SkillCatalog


_CATALOG_HEADER = "可用技能目录："
_CATALOG_EMPTY = "当前没有可用技能。"
_CATALOG_INSTRUCTION = "需要某项技能的完整说明时，调用 load_skill 并传入精确技能名称。"


def format_skill_catalog(
    catalog: SkillCatalog,
    *,
    max_characters: int = 8_000,
    instruction: str = _CATALOG_INSTRUCTION,
) -> str:
    """将元数据格式化为有界目录，不把 Skill 正文写入系统提示。"""

    if not isinstance(catalog, SkillCatalog):
        raise TypeError("技能目录必须是 SkillCatalog 对象。")
    if isinstance(max_characters, bool) or not isinstance(max_characters, int):
        raise ValueError("字段“max_characters”必须是整数。")
    if max_characters < 1:
        raise ValueError("字段“max_characters”必须大于或等于 1。")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("字段“instruction”必须是非空字符串。")

    if not catalog.metadata:
        return _CATALOG_EMPTY
    listing = "\n".join(
        f"- {metadata.name}：{metadata.description}" for metadata in catalog.metadata
    )
    formatted = "\n".join((_CATALOG_HEADER, listing, instruction.strip()))
    if len(formatted) > max_characters:
        raise ValueError(f"技能目录提示不能超过 {max_characters} 个字符。")
    return formatted
