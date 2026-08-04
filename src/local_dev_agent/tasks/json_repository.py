"""使用每任务一个 JSON 文件保存跨会话任务图的本地适配器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock

from .errors import (
    CorruptedTaskFileError,
    TaskAlreadyExistsError,
    TaskNotFoundError,
)
from .json_codec import decode_task, encode_task
from .schema import Task


_TASK_LOCKS_GUARD = Lock()
_TASK_LOCKS: dict[Path, RLock] = {}


def _lock_for(root_directory: Path) -> RLock:
    """让指向同一目录的仓储实例共享锁，避免进程内读判写竞争。"""

    resolved_directory = root_directory.resolve()
    with _TASK_LOCKS_GUARD:
        return _TASK_LOCKS.setdefault(resolved_directory, RLock())


class JsonFileTaskRepository:
    """将每个任务保存为独立、可恢复且原子替换的 JSON 文件。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("任务仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory
        self._lock = _lock_for(root_directory)

    def add(self, task: Task) -> Task:
        """新增任务文件，拒绝无锁首版中可检测到的同标识重复创建。"""

        path = self._path_for(task.task_id)
        with self._lock:
            if path.exists():
                raise TaskAlreadyExistsError(task_id=task.task_id)
            self._write_json_atomically(path, encode_task(task))
        return task

    def get(self, task_id: str) -> Task | None:
        """读取一个任务；对应文件不存在时返回空值。"""

        path = self._path_for(task_id)
        if not path.exists():
            return None
        return self._read_task(path, expected_task_id=task_id)

    def list(self) -> tuple[Task, ...]:
        """按文件名稳定读取全部任务，忽略原子写入留下的临时文件。"""

        if not self._root_directory.exists():
            return ()
        return tuple(
            self._read_task(path, expected_task_id=path.stem)
            for path in sorted(self._root_directory.glob("*.json"))
        )

    def replace(self, task: Task) -> Task:
        """原子替换已有任务，避免状态转换意外创建新任务。"""

        path = self._path_for(task.task_id)
        with self._lock:
            if not path.exists():
                raise TaskNotFoundError(task_id=task.task_id)
            self._write_json_atomically(path, encode_task(task))
        return task

    def compare_and_replace(self, *, expected: Task, replacement: Task) -> bool:
        """在同一进程内原子比较并替换任务快照，供并发认领竞争使用。"""

        if not isinstance(expected, Task) or not isinstance(replacement, Task):
            raise TypeError("expected 和 replacement 必须都是 Task 对象。")
        if expected.task_id != replacement.task_id:
            raise ValueError("比较并替换的两个任务必须具有相同标识。")

        path = self._path_for(expected.task_id)
        with self._lock:
            if not path.exists():
                return False
            if self._read_task(path, expected_task_id=expected.task_id) != expected:
                return False
            self._write_json_atomically(path, encode_task(replacement))
            return True

    def _read_task(self, path: Path, *, expected_task_id: str) -> Task:
        """将文件、信封和任务标识错误收束为仓储诊断错误。"""

        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("任务文件根节点必须是对象。")
            task = decode_task(payload)
            if task.task_id != expected_task_id:
                raise ValueError("任务文件标识不匹配。")
            return task
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CorruptedTaskFileError(path=path) from error

    @staticmethod
    def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
        """先写同目录临时文件并 fsync，再替换目标以避免半截任务快照。"""

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

    def _path_for(self, task_id: str) -> Path:
        """构建单任务路径，并拒绝可能写入仓储根目录外的标识。"""

        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or task_id in {".", ".."}
            or "/" in task_id
            or "\\" in task_id
        ):
            raise ValueError("任务标识不能包含路径分隔符。")
        return self._root_directory / f"{task_id}.json"
