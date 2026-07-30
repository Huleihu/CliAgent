"""durable Cron 定义的工作区级 JSON 仓储适配器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .errors import (
    CorruptedCronTaskFileError,
    CronTaskAlreadyExistsError,
    CronTaskNotFoundError,
)
from .json_codec import decode_tasks, encode_tasks
from .schema import CronTask, CronTaskScope

_FILE_NAME = "scheduled_tasks.json"


class JsonFileCronTaskRepository:
    """以单个版本化 JSON 文件保存可跨进程恢复的 durable 定义。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("Cron 任务仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory

    def add(self, task: CronTask) -> CronTask:
        """新增 durable 定义，拒绝同一稳定标识重复出现。"""

        self._require_durable(task)
        tasks = self._load_all()
        if any(existing.task_id == task.task_id for existing in tasks):
            raise CronTaskAlreadyExistsError(task_id=task.task_id)
        self._write_all((*tasks, task))
        return task

    def get(self, task_id: str) -> CronTask | None:
        """按标识读取 durable 定义；缺失文件或条目均返回 None。"""

        normalized_task_id = _require_task_id(task_id)
        return next(
            (
                task
                for task in self._load_all()
                if task.task_id == normalized_task_id
            ),
            None,
        )

    def list_visible_to_session(self, session_id: str) -> tuple[CronTask, ...]:
        """durable 定义属于工作区，因此对每个有效 Session 均可见。"""

        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("字段“session_id”必须是非空字符串。")
        return self._load_all()

    def replace(self, task: CronTask) -> CronTask:
        """原子替换同一 durable 定义，例如写入最近成功入队分钟。"""

        self._require_durable(task)
        tasks = self._load_all()
        if not any(existing.task_id == task.task_id for existing in tasks):
            raise CronTaskNotFoundError(task_id=task.task_id)
        replaced_tasks = tuple(
            task if existing.task_id == task.task_id else existing for existing in tasks
        )
        self._write_all(replaced_tasks)
        return task

    def remove(self, task_id: str) -> CronTask | None:
        """删除 durable 定义；不存在时不创建或改写文件。"""

        normalized_task_id = _require_task_id(task_id)
        tasks = self._load_all()
        removed_task = next(
            (task for task in tasks if task.task_id == normalized_task_id),
            None,
        )
        if removed_task is None:
            return None
        self._write_all(
            tuple(task for task in tasks if task.task_id != normalized_task_id)
        )
        return removed_task

    def _load_all(self) -> tuple[CronTask, ...]:
        """读取 durable 集合；单条坏记录已由编解码器安全跳过。"""

        path = self._path
        if not path.exists():
            return ()
        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("Cron 任务文件根节点必须是对象。")
            return decode_tasks(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CorruptedCronTaskFileError(path=path) from error

    def _write_all(self, tasks: tuple[CronTask, ...]) -> None:
        """以同目录临时文件和原子替换保存完整 durable 集合。"""

        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".scheduled_tasks.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                json.dump(encode_tasks(tasks), file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @property
    def _path(self) -> Path:
        return self._root_directory / _FILE_NAME

    @staticmethod
    def _require_durable(task: CronTask) -> None:
        """防止 session-only 定义意外获得跨进程持久化语义。"""

        if not isinstance(task, CronTask):
            raise TypeError("Cron 任务仓储只能保存 CronTask 对象。")
        if task.scope is not CronTaskScope.DURABLE:
            raise ValueError("JSON Cron 仓储只能保存 durable 任务。")


def _require_task_id(task_id: str) -> str:
    """拒绝空白或含路径分隔符的标识，避免后续实现扩大文件边界。"""

    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("字段“task_id”必须是非空字符串。")
    return task_id.strip()
