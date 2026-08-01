"""Team 协议请求状态的版本化 JSON 文件仓储适配器。"""

from __future__ import annotations

from pathlib import Path

from .errors import (
    CorruptedTeamFileError,
    TeamEntityNotFoundError,
    TeamProtocolStateAlreadyExistsError,
)
from .json_codec import decode_protocol_state, encode_protocol_state
from .json_support import read_json_object, require_safe_identifier, write_json_atomically
from .protocol_state import TeamProtocolState
from .protocol_types import TeamProtocolStatus


class JsonFileTeamProtocolStateRepository:
    """按 Team 目录、每项一个 JSON 文件保存协议请求状态。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("Team 协议状态仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory

    def add(self, state: TeamProtocolState) -> TeamProtocolState:
        """新增 pending 协议请求，拒绝跨 Team 重复使用 request_id。"""

        if not isinstance(state, TeamProtocolState):
            raise TypeError("Team 协议状态仓储只能保存 TeamProtocolState 对象。")
        if self.get(state.request_id) is not None:
            raise TeamProtocolStateAlreadyExistsError(request_id=state.request_id)
        write_json_atomically(
            self._path_for(state.team_id, state.request_id),
            encode_protocol_state(state),
        )
        return state

    def get(self, request_id: str) -> TeamProtocolState | None:
        """在全部 Team 目录中按 request_id 读取协议状态。"""

        safe_request_id = require_safe_identifier("request_id", request_id)
        paths = tuple(sorted(self._root_directory.glob(f"*/protocols/{safe_request_id}.json")))
        if not paths:
            return None
        if len(paths) > 1:
            raise CorruptedTeamFileError(path=self._root_directory)
        return self._read_state(paths[0], expected_request_id=safe_request_id)

    def list_pending_for_team(self, team_id: str) -> tuple[TeamProtocolState, ...]:
        """按创建时间和 request_id 稳定列出尚未解决的协议请求。"""

        safe_team_id = require_safe_identifier("team_id", team_id)
        directory = self._root_directory / safe_team_id / "protocols"
        if not directory.exists():
            return ()
        states = tuple(
            self._read_state(path, expected_request_id=path.stem)
            for path in sorted(directory.glob("*.json"))
        )
        return tuple(
            sorted(
                (
                    state
                    for state in states
                    if state.status is TeamProtocolStatus.PENDING
                ),
                key=lambda state: (state.created_at, state.request_id),
            )
        )

    def replace(self, state: TeamProtocolState) -> TeamProtocolState:
        """原子替换已有协议状态，不允许状态迁移意外新建记录。"""

        if not isinstance(state, TeamProtocolState):
            raise TypeError("Team 协议状态仓储只能保存 TeamProtocolState 对象。")
        path = self._path_for(state.team_id, state.request_id)
        if not path.exists():
            raise TeamEntityNotFoundError(
                entity_name="Team 协议请求",
                entity_id=state.request_id,
            )
        write_json_atomically(path, encode_protocol_state(state))
        return state

    def _path_for(self, team_id: str, request_id: str) -> Path:
        return (
            self._root_directory
            / require_safe_identifier("team_id", team_id)
            / "protocols"
            / f"{require_safe_identifier('request_id', request_id)}.json"
        )

    @staticmethod
    def _read_state(path: Path, *, expected_request_id: str) -> TeamProtocolState:
        try:
            state = decode_protocol_state(read_json_object(path))
            if state.request_id != expected_request_id:
                raise ValueError("Team 协议请求文件标识不匹配。")
            return state
        except (OSError, ValueError) as error:
            raise CorruptedTeamFileError(path=path) from error
