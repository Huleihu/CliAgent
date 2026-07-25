"""使用单个 JSON 文件保存平铺待办清单的本地仓储适配器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .errors import CorruptedTodoFileError
from .json_codec import decode_snapshot, encode_snapshot
from .schema import TodoSnapshot


class JsonFileTodoRepository:
    """将待办清单保存为可跨进程恢复的版本化 JSON 文件。"""

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory

    def load(self, todo_list_id: str) -> TodoSnapshot:
        """读取指定清单；尚未保存时返回同标识的空快照。"""

        path = self._path_for(todo_list_id)
        if not path.exists():
            return TodoSnapshot.create(todo_list_id=todo_list_id)

        snapshot = self._read_snapshot(path)
        if snapshot.todo_list_id != todo_list_id:
            raise CorruptedTodoFileError(path=path)
        return snapshot

    def replace(self, snapshot: TodoSnapshot) -> TodoSnapshot:
        """将完整快照原子替换为指定清单的唯一当前状态。"""

        path = self._path_for(snapshot.todo_list_id)
        self._write_json_atomically(path, encode_snapshot(snapshot))
        return snapshot

    def _read_snapshot(self, path: Path) -> TodoSnapshot:
        """读取文件并将格式问题归一为明确的仓储错误。"""

        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("待办清单文件根节点必须是对象。")
            return decode_snapshot(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CorruptedTodoFileError(path=path) from error

    def _write_json_atomically(self, path: Path, payload: dict[str, object]) -> None:
        """先写入同目录临时文件，再替换目标文件以避免半截快照。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _path_for(self, todo_list_id: str) -> Path:
        """构建清单文件路径，并拒绝可能越界的标识。"""

        if (
            not isinstance(todo_list_id, str)
            or not todo_list_id.strip()
            or todo_list_id in {".", ".."}
            or "/" in todo_list_id
            or "\\" in todo_list_id
        ):
            raise ValueError("待办清单标识不能包含路径分隔符。")
        return self._root_directory / f"{todo_list_id}.json"
