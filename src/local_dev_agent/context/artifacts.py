"""保存完整工具结果、供压缩后的上下文按引用使用的本地 Artifact。"""

from __future__ import annotations

import hashlib
import json
import os
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


class FileSystemToolResultArtifactStore:
    """以内容摘要命名的 JSON 文件保存工具结果，避免重复覆盖完整输出。"""

    _SCHEMA_VERSION = 1

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory

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
