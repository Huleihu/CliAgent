"""工作区级长期记忆的 Markdown 文件仓储。"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .errors import CorruptedMemoryFileError
from .frontmatter import parse_memory_document, render_memory_document
from .schema import MemoryCatalog, MemoryEntry, MemoryType


class FileSystemMemoryRepository:
    """将每条长期记忆保存为独立 Markdown，并维护受控的 Markdown 索引。"""

    _INDEX_FILENAME = "MEMORY.md"

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("root_directory 必须是 Path 对象。")
        self._root_directory = root_directory

    def list_entries(self) -> MemoryCatalog:
        """扫描受控目录并返回稳定快照，绝不把索引文件作为一条记忆。"""

        if not self._root_directory.exists():
            return MemoryCatalog()
        if not self._root_directory.is_dir():
            raise CorruptedMemoryFileError(self._root_directory)
        entries = tuple(
            sorted(
                (self._read_entry(path) for path in self._entry_paths()),
                key=lambda entry: entry.memory_id,
            )
        )
        try:
            return MemoryCatalog(entries=entries)
        except ValueError as error:
            raise CorruptedMemoryFileError(self._root_directory) from error

    def get(self, memory_id: str) -> MemoryEntry | None:
        """按精确标识读取单个受控文件，不接受任意相对路径。"""

        path = self._path_for(memory_id)
        if not path.exists():
            return None
        return self._read_entry(path)

    def save(self, entry: MemoryEntry) -> MemoryEntry:
        """原子写入条目后从全部条目重建索引，避免维护两份业务真相。"""

        if not isinstance(entry, MemoryEntry):
            raise TypeError("entry 必须是 MemoryEntry 对象。")
        self._write_text_atomically(self._path_for(entry.memory_id), render_memory_document(entry))
        self._write_text_atomically(self._index_path, self._render_index(self.list_entries()))
        return entry

    @property
    def _index_path(self) -> Path:
        return self._root_directory / self._INDEX_FILENAME

    def _entry_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for path in self._root_directory.glob("*.md"):
            if path.name == self._INDEX_FILENAME:
                continue
            if not path.is_file() or not self._is_within_root(path):
                raise CorruptedMemoryFileError(path)
            paths.append(path)
        return tuple(paths)

    def _read_entry(self, path: Path) -> MemoryEntry:
        if not path.is_file() or not self._is_within_root(path):
            raise CorruptedMemoryFileError(path)
        try:
            entry = parse_memory_document(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise CorruptedMemoryFileError(path) from error
        if path.name != f"{entry.memory_id}.md":
            raise CorruptedMemoryFileError(path)
        return entry

    def _path_for(self, memory_id: str) -> Path:
        entry = MemoryEntry(
            memory_id=memory_id,
            memory_type=MemoryType.USER,
            description="占位描述",
            content="占位正文",
        )
        return self._root_directory / f"{entry.memory_id}.md"

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._root_directory.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _render_index(catalog: MemoryCatalog) -> str:
        return "".join(
            f"- [{entry.memory_id}]({entry.memory_id}.md) — {entry.description}\n"
            for entry in catalog.entries
        )

    @staticmethod
    def _write_text_atomically(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
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
