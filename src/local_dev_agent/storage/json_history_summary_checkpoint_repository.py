"""使用 JSON 文件保存独立、原子化的历史摘要检查点。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from local_dev_agent.context.checkpoints import HistorySummaryCheckpoint

from .errors import CorruptedHistorySummaryCheckpointFileError
from .history_summary_checkpoint_json_codec import (
    decode_history_summary_checkpoint,
    encode_history_summary_checkpoint,
)


class JsonFileHistorySummaryCheckpointRepository:
    """按会话保存单个可替换检查点，与追加式 Transcript 完全隔离。"""

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory

    def load(self, session_id: str) -> HistorySummaryCheckpoint | None:
        """读取会话检查点；文件缺失表示尚未建立检查点。"""

        path = self._path_for(session_id)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("历史摘要检查点文件根节点必须是对象。")
            checkpoint = decode_history_summary_checkpoint(payload)
            if checkpoint.session_id != session_id:
                raise ValueError("历史摘要检查点文件会话标识不匹配。")
            return checkpoint
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CorruptedHistorySummaryCheckpointFileError(path=path) from error

    def save(self, checkpoint: HistorySummaryCheckpoint) -> None:
        """以同目录临时文件和原子替换保存完整检查点。"""

        if not isinstance(checkpoint, HistorySummaryCheckpoint):
            raise TypeError("checkpoint 必须是 HistorySummaryCheckpoint 对象。")
        self._write_json_atomically(
            self._path_for(checkpoint.session_id),
            encode_history_summary_checkpoint(checkpoint),
        )

    def _path_for(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not session_id or Path(session_id).name != session_id:
            raise ValueError("会话标识不能包含路径分隔符。")
        return self._root_directory / "history-summary-checkpoints" / f"{session_id}.json"

    @staticmethod
    def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
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
