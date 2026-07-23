"""使用单实体 JSON 文件保存状态快照的本地仓储适配器。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, TypeVar

from local_dev_agent.domain.state import RunState, SessionState, StepState

from .errors import CorruptedStateFileError, StateVersionConflictError
from .state_json_codec import (
    decode_run,
    decode_session,
    decode_step,
    encode_run,
    encode_session,
    encode_step,
)

StateT = TypeVar("StateT", SessionState, RunState, StepState)


class JsonFileStateRepository:
    """将状态快照保存为可检查、可跨进程恢复的 JSON 文件。"""

    def __init__(self, root_directory: Path) -> None:
        self._root_directory = root_directory

    def save_session(self, state: SessionState) -> None:
        """保存会话快照，并防止旧版本覆盖新版本。"""

        self._save(
            state=state,
            entity_name="会话",
            path=self._path_for("sessions", state.session_id),
            encoder=encode_session,
            decoder=decode_session,
        )

    def get_session(self, session_id: str) -> SessionState | None:
        """按标识读取会话；文件不存在时返回空值。"""

        return self._get(
            path=self._path_for("sessions", session_id),
            decoder=decode_session,
        )

    def save_run(self, state: RunState) -> None:
        """保存运行快照，并防止旧版本覆盖新版本。"""

        self._save(
            state=state,
            entity_name="运行",
            path=self._path_for("runs", state.run_id),
            encoder=encode_run,
            decoder=decode_run,
        )

    def get_run(self, run_id: str) -> RunState | None:
        """按标识读取运行；文件不存在时返回空值。"""

        return self._get(
            path=self._path_for("runs", run_id),
            decoder=decode_run,
        )

    def list_runs(self, session_id: str) -> tuple[RunState, ...]:
        """扫描运行目录，读取属于指定会话的运行。"""

        return tuple(
            state
            for path in self._entity_paths("runs")
            if (state := self._get(path=path, decoder=decode_run)) is not None
            and state.session_id == session_id
        )

    def save_step(self, state: StepState) -> None:
        """保存步骤快照，并防止旧版本覆盖新版本。"""

        self._save(
            state=state,
            entity_name="步骤",
            path=self._path_for("steps", state.step_id),
            encoder=encode_step,
            decoder=decode_step,
        )

    def get_step(self, step_id: str) -> StepState | None:
        """按标识读取步骤；文件不存在时返回空值。"""

        return self._get(
            path=self._path_for("steps", step_id),
            decoder=decode_step,
        )

    def list_steps(self, run_id: str) -> tuple[StepState, ...]:
        """扫描步骤目录，读取属于指定运行的步骤。"""

        return tuple(
            state
            for path in self._entity_paths("steps")
            if (state := self._get(path=path, decoder=decode_step)) is not None
            and state.run_id == run_id
        )

    def _save(
        self,
        *,
        state: StateT,
        entity_name: str,
        path: Path,
        encoder: Callable[[StateT], dict[str, object]],
        decoder: Callable[[dict[str, Any]], StateT],
    ) -> None:
        """校验版本后原子替换文件，避免留下半截快照。"""

        existing = self._get(path=path, decoder=decoder)
        expected_version = 1 if existing is None else existing.state_version + 1
        if state.state_version != expected_version:
            raise StateVersionConflictError(
                entity_name=entity_name,
                entity_id=self._state_id(state),
            )
        self._write_json_atomically(path, encoder(state))

    def _get(
        self,
        *,
        path: Path,
        decoder: Callable[[dict[str, Any]], StateT],
    ) -> StateT | None:
        """读取文件并将格式问题归一为明确的仓储错误。"""

        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                raise ValueError("状态文件根节点必须是对象。")
            return decoder(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CorruptedStateFileError(path=path) from error

    def _write_json_atomically(self, path: Path, payload: dict[str, object]) -> None:
        """先持久化临时文件，再原子替换目标文件。"""

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

    def _path_for(self, directory_name: str, entity_id: str) -> Path:
        """构建实体文件路径，并拒绝可能越界的标识。"""

        if not entity_id or Path(entity_id).name != entity_id:
            raise ValueError("状态标识不能包含路径分隔符。")
        return self._root_directory / directory_name / f"{entity_id}.json"

    def _entity_paths(self, directory_name: str) -> tuple[Path, ...]:
        """返回稳定顺序的实体文件列表，便于测试与后续替换实现。"""

        directory = self._root_directory / directory_name
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("*.json")))

    @staticmethod
    def _state_id(state: StateT) -> str:
        """从不同状态类型提取用于错误信息的实体标识。"""

        if isinstance(state, SessionState):
            return state.session_id
        if isinstance(state, RunState):
            return state.run_id
        return state.step_id
