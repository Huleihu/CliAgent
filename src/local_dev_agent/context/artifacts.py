"""保存完整工具结果、供压缩后的上下文按引用使用的本地 Artifact。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol


def _require_nonempty_text(field_name: str, value: str) -> str:
    """拒绝空标识和路径片段，避免 Artifact 引用失去可追溯性。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ToolResultArtifact:
    """一份已落盘工具结果的稳定引用，不携带完整正文。"""

    relative_path: str
    content_sha256: str
    content_bytes: int

    def __post_init__(self) -> None:
        """限制引用为受控相对路径，并校验摘要和字节数。"""

        relative_path = _require_nonempty_text("relative_path", self.relative_path)
        if (
            Path(relative_path).is_absolute()
            or "\\" in relative_path
            or ".." in relative_path.split("/")
        ):
            raise ValueError("字段“relative_path”必须是受控的相对路径。")
        digest = _require_nonempty_text("content_sha256", self.content_sha256)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("字段“content_sha256”必须是 SHA-256 十六进制摘要。")
        if (
            isinstance(self.content_bytes, bool)
            or not isinstance(self.content_bytes, int)
            or self.content_bytes < 1
        ):
            raise ValueError("字段“content_bytes”必须是正整数。")
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(self, "content_sha256", digest)


class ArtifactReadError(RuntimeError):
    """当 Artifact 引用、完整性或封装不符合读取边界时抛出。"""


@dataclass(frozen=True, slots=True)
class ToolResultArtifactPage:
    """一段可安全回填模型的 Artifact 正文分页，不暴露存储根目录。"""

    artifact_ref: str
    content: str
    offset: int
    next_offset: int | None
    total_characters: int

    def __post_init__(self) -> None:
        """固定分页边界，避免工具返回越界偏移或非文本正文。"""

        _require_nonempty_text("artifact_ref", self.artifact_ref)
        if not isinstance(self.content, str):
            raise ValueError("字段“content”必须是字符串。")
        for field_name, value in (
            ("offset", self.offset),
            ("total_characters", self.total_characters),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"字段“{field_name}”必须是非负整数。")
        if self.offset > self.total_characters:
            raise ValueError("字段“offset”不能超过 Artifact 正文长度。")
        if self.next_offset is not None and (
            isinstance(self.next_offset, bool)
            or not isinstance(self.next_offset, int)
            or self.next_offset <= self.offset
            or self.next_offset > self.total_characters
        ):
            raise ValueError("字段“next_offset”必须是正文范围内、且大于 offset 的整数。")

    @property
    def truncated(self) -> bool:
        """表示调用方可继续使用 next_offset 读取后续正文。"""

        return self.next_offset is not None


class ToolResultArtifactStore(Protocol):
    """保存完整工具结果并返回可安全注入模型上下文的引用。"""

    def persist(
        self,
        *,
        tool_use_id: str,
        content: Mapping[str, object],
        is_error: bool,
    ) -> ToolResultArtifact:
        """持久化完整结果；调用方只保留返回的轻量引用。"""


class ToolResultArtifactReader(Protocol):
    """按受控引用读取已保存工具结果的有限正文片段。"""

    def read_text_page(
        self,
        *,
        artifact_ref: str,
        offset: int,
        max_characters: int,
    ) -> ToolResultArtifactPage:
        """返回 Artifact 原始 content 的稳定 JSON 文本分页。"""


class FileSystemToolResultArtifactStore:
    """以内容摘要命名的 JSON 文件保存工具结果，避免重复覆盖完整输出。"""

    _SCHEMA_VERSION = 1
    _ARTIFACT_REF_PATTERN = re.compile(r"tool-results/([0-9a-f]{64})\.json\Z")

    def __init__(self, root_directory: Path, *, max_read_bytes: int = 50_000_000) -> None:
        if isinstance(max_read_bytes, bool) or not isinstance(max_read_bytes, int):
            raise ValueError("字段“max_read_bytes”必须是整数。")
        if max_read_bytes < 1:
            raise ValueError("字段“max_read_bytes”必须大于或等于 1。")
        self._root_directory = root_directory
        self._max_read_bytes = max_read_bytes

    def persist(
        self,
        *,
        tool_use_id: str,
        content: Mapping[str, object],
        is_error: bool,
    ) -> ToolResultArtifact:
        """原子写入完整 JSON 结果，并以内容摘要生成稳定引用。"""

        tool_use_id = _require_nonempty_text("tool_use_id", tool_use_id)
        if not isinstance(content, Mapping):
            raise ValueError("字段“content”必须是对象。")
        if not isinstance(is_error, bool):
            raise ValueError("字段“is_error”必须是布尔值。")

        copied_content = dict(content)
        content_bytes = self._serialize_json(copied_content)
        payload_bytes = self._serialize_json(
            {
                "schema_version": self._SCHEMA_VERSION,
                "tool_use_id": tool_use_id,
                "is_error": is_error,
                "content": copied_content,
            }
        )
        digest = hashlib.sha256(payload_bytes).hexdigest()
        relative_path = f"tool-results/{digest}.json"
        path = self._root_directory / Path(relative_path)
        if not path.exists():
            self._write_bytes_atomically(path, payload_bytes)
        return ToolResultArtifact(
            relative_path=relative_path,
            content_sha256=digest,
            content_bytes=len(content_bytes),
        )

    def read_text_page(
        self,
        *,
        artifact_ref: str,
        offset: int,
        max_characters: int,
    ) -> ToolResultArtifactPage:
        """验证受控引用和完整性后，读取原始结果 content 的有限 JSON 文本片段。"""

        digest = self._artifact_digest(artifact_ref)
        offset = self._require_nonnegative_integer("offset", offset)
        max_characters = self._require_positive_integer("max_characters", max_characters)
        path = self._resolve_artifact_path(artifact_ref)
        try:
            payload_bytes = path.read_bytes()
        except OSError as error:
            raise ArtifactReadError("无法读取指定的 Artifact。") from error
        if len(payload_bytes) > self._max_read_bytes:
            raise ArtifactReadError("指定的 Artifact 超过受控读取大小限制。")
        if hashlib.sha256(payload_bytes).hexdigest() != digest:
            raise ArtifactReadError("指定的 Artifact 摘要校验失败。")
        content = self._read_payload_content(payload_bytes)
        serialized_content = self._serialize_json(content).decode("utf-8")
        total_characters = len(serialized_content)
        if offset > total_characters:
            raise ArtifactReadError("字段“offset”不能超过 Artifact 正文长度。")
        content_page = serialized_content[offset : offset + max_characters]
        next_offset = offset + len(content_page)
        return ToolResultArtifactPage(
            artifact_ref=artifact_ref,
            content=content_page,
            offset=offset,
            next_offset=next_offset if next_offset < total_characters else None,
            total_characters=total_characters,
        )

    @classmethod
    def _artifact_digest(cls, artifact_ref: str) -> str:
        """只接受摘要命名的标准 Artifact 引用，不把它解释为任意文件路径。"""

        if not isinstance(artifact_ref, str):
            raise ArtifactReadError("字段“artifact_ref”必须是字符串。")
        match = cls._ARTIFACT_REF_PATTERN.fullmatch(artifact_ref)
        if match is None:
            raise ArtifactReadError("字段“artifact_ref”不是受支持的 Artifact 引用。")
        return match.group(1)

    @staticmethod
    def _require_nonnegative_integer(field_name: str, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ArtifactReadError(f"字段“{field_name}”必须是非负整数。")
        return value

    @staticmethod
    def _require_positive_integer(field_name: str, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ArtifactReadError(f"字段“{field_name}”必须是正整数。")
        return value

    def _resolve_artifact_path(self, artifact_ref: str) -> Path:
        """解析后再次确认路径在 Artifact 根目录内，阻止链接或路径替换越界。"""

        root_directory = self._root_directory.resolve()
        try:
            path = (root_directory / Path(artifact_ref)).resolve(strict=True)
        except OSError as error:
            raise ArtifactReadError("找不到指定的 Artifact。") from error
        try:
            path.relative_to(root_directory)
        except ValueError as error:
            raise ArtifactReadError("指定的 Artifact 路径越过受控根目录。") from error
        if not path.is_file():
            raise ArtifactReadError("指定的 Artifact 不是普通文件。")
        return path

    @classmethod
    def _read_payload_content(cls, payload_bytes: bytes) -> dict[str, object]:
        """校验版本化封装，确保读取对象确为本存储格式的工具结果。"""

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactReadError("指定的 Artifact 不是有效 UTF-8 JSON 文件。") from error
        if not isinstance(payload, Mapping):
            raise ArtifactReadError("指定的 Artifact 封装格式无效。")
        if payload.get("schema_version") != cls._SCHEMA_VERSION:
            raise ArtifactReadError("指定的 Artifact 使用了不受支持的版本。")
        if not isinstance(payload.get("tool_use_id"), str) or not payload["tool_use_id"].strip():
            raise ArtifactReadError("指定的 Artifact 缺少有效工具调用标识。")
        if not isinstance(payload.get("is_error"), bool):
            raise ArtifactReadError("指定的 Artifact 缺少有效错误标识。")
        content = payload.get("content")
        if not isinstance(content, Mapping):
            raise ArtifactReadError("指定的 Artifact 缺少有效结果对象。")
        return dict(content)

    @staticmethod
    def _serialize_json(value: object) -> bytes:
        """使用稳定 JSON 表示，确保摘要、预览来源与预算计算一致。"""

        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("工具结果必须只包含 JSON 原生值。") from error

    @staticmethod
    def _write_bytes_atomically(path: Path, content: bytes) -> None:
        """先同步临时文件再替换，避免中断后暴露半截 Artifact。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
