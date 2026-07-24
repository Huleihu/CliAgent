"""使用 JSON 文件保存跨 Run 会话消息 Transcript 的本地适配器。"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

from local_dev_agent.models import ModelMessage

from .conversation_json_codec import decode_conversation, encode_conversation
from .errors import CorruptedConversationFileError


class JsonFileConversationRepository:
    """按会话保存追加式消息历史，支持跨进程恢复。"""

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory

    def get_messages(self, session_id: str) -> tuple[ModelMessage, ...]:
        """读取一个会话的完整历史；文件不存在时返回空元组。"""

        path = self._path_for(session_id)
        if not path.exists():
            return ()
        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("会话消息文件根节点必须是对象。")
            stored_session_id, messages = decode_conversation(payload)
            if stored_session_id != session_id:
                raise ValueError("会话消息文件标识不匹配。")
            return messages
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CorruptedConversationFileError(path=path) from error

    def append_messages(self, session_id: str, messages: Sequence[ModelMessage]) -> None:
        """原子地追加消息，避免进程中断后留下半截 Transcript。"""

        if not messages:
            return
        if not all(isinstance(message, ModelMessage) for message in messages):
            raise TypeError("会话消息必须都是 ModelMessage 对象。")
        existing_messages = self.get_messages(session_id)
        payload = encode_conversation(session_id, existing_messages + tuple(messages))
        self._write_json_atomically(self._path_for(session_id), payload)

    def _path_for(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("会话标识不能包含路径分隔符。")
        return self._root_directory / "conversations" / f"{session_id}.json"

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
