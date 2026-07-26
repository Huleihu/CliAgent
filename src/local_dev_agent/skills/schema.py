"""S07 技能加载使用的不可变领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


def _require_nonempty_text(field_name: str, value: str) -> str:
    """规范化展示文本，避免空白值进入技能目录或查询键。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """技能目录中始终可见的最小元数据。"""

    name: str
    description: str

    def __post_init__(self) -> None:
        """收束名称和单行描述，保持后续系统提示的稳定边界。"""

        object.__setattr__(self, "name", _require_nonempty_text("name", self.name))
        description = _require_nonempty_text("description", self.description)
        object.__setattr__(self, "description", " ".join(description.split()))


@dataclass(frozen=True, slots=True)
class SkillDocument:
    """一份技能文档的完整不可变快照，不等同于系统提示内容。"""

    metadata: SkillMetadata
    content: str

    def __post_init__(self) -> None:
        """确保目录元数据与按需返回的原始文档均可安全使用。"""

        if not isinstance(self.metadata, SkillMetadata):
            raise ValueError("字段“metadata”必须是 SkillMetadata 对象。")
        _require_nonempty_text("content", self.content)
