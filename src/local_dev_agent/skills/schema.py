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
    source_directory: str
    content: str

    def __post_init__(self) -> None:
        """确保目录元数据与按需返回的原始文档均可安全使用。"""

        if not isinstance(self.metadata, SkillMetadata):
            raise ValueError("字段“metadata”必须是 SkillMetadata 对象。")
        source_directory = _require_nonempty_text(
            "source_directory", self.source_directory
        )
        if source_directory.startswith("/") or "\\" in source_directory or ".." in source_directory.split("/"):
            raise ValueError("字段“source_directory”必须是受控的相对目录。")
        object.__setattr__(self, "source_directory", source_directory)
        _require_nonempty_text("content", self.content)


@dataclass(frozen=True, slots=True)
class SkillCatalog:
    """一次启动扫描生成的技能目录不可变快照。"""

    documents: tuple[SkillDocument, ...] = ()

    def __post_init__(self) -> None:
        """拒绝不稳定排序与重复查询键，避免模型看到含糊目录。"""

        if not isinstance(self.documents, tuple) or not all(
            isinstance(document, SkillDocument) for document in self.documents
        ):
            raise ValueError("技能目录必须是 SkillDocument 元组。")
        names = tuple(document.metadata.name for document in self.documents)
        if names != tuple(sorted(names)):
            raise ValueError("技能目录必须按技能名称升序排列。")
        if len(set(names)) != len(names):
            raise ValueError("技能目录不能包含重复名称。")

    @property
    def metadata(self) -> tuple[SkillMetadata, ...]:
        """返回仅供目录展示的元数据，避免调用方误用完整正文。"""

        return tuple(document.metadata for document in self.documents)

    def get_document(self, name: str) -> SkillDocument | None:
        """按精确技能名称查询文档，不将名称解释为文件路径。"""

        normalized_name = _require_nonempty_text("name", name)
        return next(
            (
                document
                for document in self.documents
                if document.metadata.name == normalized_name
            ),
            None,
        )
