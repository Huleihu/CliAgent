"""受工作区边界保护的本地技能目录加载器。"""

from __future__ import annotations

from pathlib import Path

from .errors import SkillCatalogLoadError, SkillFrontmatterError
from .frontmatter import parse_skill_frontmatter
from .schema import SkillCatalog, SkillDocument


class FileSystemSkillCatalogLoader:
    """从工作区的单一 skills 目录创建稳定的技能快照。"""

    _MANIFEST_FILE_NAME = "SKILL.md"

    def __init__(
        self,
        workspace: Path,
        *,
        directory_name: str = "skills",
        max_documents: int = 64,
        max_document_bytes: int = 50_000,
    ) -> None:
        if not isinstance(workspace, Path):
            raise TypeError("工作区根目录必须是 Path 对象。")
        self._workspace = workspace.resolve()
        if not self._workspace.is_dir():
            raise SkillCatalogLoadError(
                f"工作区目录不存在或不是目录：{self._workspace}。"
            )
        self._directory_name = self._validate_directory_name(directory_name)
        self._max_documents = self._validate_positive_integer(
            "max_documents", max_documents
        )
        self._max_document_bytes = self._validate_positive_integer(
            "max_document_bytes", max_document_bytes
        )

    def load(self) -> SkillCatalog:
        """扫描受控目录并创建完整快照，缺少目录时返回空目录。"""

        skills_root = (self._workspace / self._directory_name).resolve()
        if not self._contains_workspace_path(skills_root):
            raise SkillCatalogLoadError("技能目录超出工作区边界。")
        if not skills_root.exists():
            return SkillCatalog()
        if not skills_root.is_dir():
            raise SkillCatalogLoadError(f"技能目录不是目录：{skills_root}。")

        documents: list[SkillDocument] = []
        known_names: set[str] = set()
        for skill_directory in sorted(skills_root.iterdir(), key=lambda path: path.name):
            if not skill_directory.is_dir():
                continue
            resolved_directory = skill_directory.resolve()
            if not self._contains_path(skills_root, resolved_directory):
                raise SkillCatalogLoadError(
                    f"技能目录“{skill_directory.name}”超出受控技能目录边界。"
                )
            manifest = skill_directory / self._MANIFEST_FILE_NAME
            if not manifest.exists():
                continue
            if not manifest.is_file():
                raise SkillCatalogLoadError(
                    f"技能清单不是普通文件：{manifest}。"
                )
            resolved_manifest = manifest.resolve()
            if not self._contains_path(skills_root, resolved_manifest):
                raise SkillCatalogLoadError(
                    f"技能清单“{skill_directory.name}/{self._MANIFEST_FILE_NAME}”超出受控技能目录边界。"
                )
            content = self._read_manifest(resolved_manifest)
            try:
                metadata = parse_skill_frontmatter(content)
            except SkillFrontmatterError as error:
                raise SkillCatalogLoadError(
                    f"技能清单“{resolved_manifest}”格式无效：{error}"
                ) from error
            if metadata.name in known_names:
                raise SkillCatalogLoadError(f"技能目录包含重复名称：{metadata.name}。")
            known_names.add(metadata.name)
            documents.append(
                SkillDocument(
                    metadata=metadata,
                    source_directory=skill_directory.relative_to(
                        self._workspace
                    ).as_posix(),
                    content=content,
                )
            )
            if len(documents) > self._max_documents:
                raise SkillCatalogLoadError(
                    f"技能目录中的文档数量不能超过 {self._max_documents}。"
                )

        return SkillCatalog(
            documents=tuple(sorted(documents, key=lambda document: document.metadata.name))
        )

    def _read_manifest(self, manifest: Path) -> str:
        """以大小受限的 UTF-8 字节读取完整清单，避免启动时无界加载。"""

        try:
            content = manifest.read_bytes()
        except OSError as error:
            raise SkillCatalogLoadError(f"无法读取技能清单“{manifest}”。") from error
        if len(content) > self._max_document_bytes:
            raise SkillCatalogLoadError(
                f"技能清单“{manifest}”不能超过 {self._max_document_bytes} 字节。"
            )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillCatalogLoadError(f"技能清单“{manifest}”不是 UTF-8 文本。") from error

    def _contains_workspace_path(self, path: Path) -> bool:
        return self._contains_path(self._workspace, path)

    @staticmethod
    def _contains_path(root: Path, path: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_directory_name(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("字段“directory_name”必须是非空字符串。")
        candidate = Path(value)
        if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name != value:
            raise ValueError("字段“directory_name”必须是单层相对目录名称。")
        return value

    @staticmethod
    def _validate_positive_integer(field_name: str, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"字段“{field_name}”必须是大于或等于 1 的整数。")
        return value
