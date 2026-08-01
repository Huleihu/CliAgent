"""Team 与成员身份的 JSON 文件仓储适配器。"""

from __future__ import annotations

from pathlib import Path

from .errors import (
    CorruptedTeamFileError,
    TeamAlreadyExistsError,
    TeamEntityNotFoundError,
    TeamMemberAlreadyExistsError,
)
from .json_codec import decode_member, decode_team, encode_member, encode_team
from .json_support import read_json_object, require_safe_identifier, write_json_atomically
from .schema import Team, TeamMember


class JsonFileTeamRepository:
    """按 Team 独立目录保存 Team 配置快照。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("Team 仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory

    def add(self, team: Team) -> Team:
        """新增 Team 配置，拒绝同标识覆盖。"""

        if not isinstance(team, Team):
            raise TypeError("Team 仓储只能保存 Team 对象。")
        path = self._path_for(team.team_id)
        if path.exists():
            raise TeamAlreadyExistsError(team_id=team.team_id)
        write_json_atomically(path, encode_team(team))
        return team

    def get(self, team_id: str) -> Team | None:
        """读取 Team；文件不存在时返回空值。"""

        path = self._path_for(team_id)
        if not path.exists():
            return None
        return self._read_team(path, expected_team_id=team_id)

    def replace(self, team: Team) -> Team:
        """原子替换已有 Team 配置。"""

        if not isinstance(team, Team):
            raise TypeError("Team 仓储只能保存 Team 对象。")
        path = self._path_for(team.team_id)
        if not path.exists():
            raise TeamEntityNotFoundError(entity_name="Team", entity_id=team.team_id)
        write_json_atomically(path, encode_team(team))
        return team

    def _path_for(self, team_id: str) -> Path:
        return self._root_directory / require_safe_identifier("team_id", team_id) / "team.json"

    @staticmethod
    def _read_team(path: Path, *, expected_team_id: str) -> Team:
        try:
            team = decode_team(read_json_object(path))
            if team.team_id != expected_team_id:
                raise ValueError("Team 文件标识不匹配。")
            return team
        except (OSError, ValueError) as error:
            raise CorruptedTeamFileError(path=path) from error


class JsonFileTeamMemberRepository:
    """按 Team 目录保存成员身份，成员标识在仓储根下保持唯一。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("Team 成员仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory

    def add(self, member: TeamMember) -> TeamMember:
        """新增成员，扫描根目录拒绝跨 Team 的重复成员标识。"""

        if not isinstance(member, TeamMember):
            raise TypeError("Team 成员仓储只能保存 TeamMember 对象。")
        if self.get(member.member_id) is not None:
            raise TeamMemberAlreadyExistsError(member_id=member.member_id)
        write_json_atomically(self._path_for(member.team_id, member.member_id), encode_member(member))
        return member

    def get(self, member_id: str) -> TeamMember | None:
        """在全部 Team 目录中按稳定路径查找成员。"""

        safe_member_id = require_safe_identifier("member_id", member_id)
        paths = tuple(sorted(self._root_directory.glob(f"*/members/{safe_member_id}.json")))
        if not paths:
            return None
        if len(paths) > 1:
            raise CorruptedTeamFileError(path=self._root_directory)
        return self._read_member(paths[0], expected_member_id=safe_member_id)

    def list_for_team(self, team_id: str) -> tuple[TeamMember, ...]:
        """按成员文件名稳定返回一个 Team 的成员快照。"""

        safe_team_id = require_safe_identifier("team_id", team_id)
        directory = self._root_directory / safe_team_id / "members"
        if not directory.exists():
            return ()
        return tuple(
            self._read_member(path, expected_member_id=path.stem)
            for path in sorted(directory.glob("*.json"))
        )

    def replace(self, member: TeamMember) -> TeamMember:
        """原子替换同一 Team 中既有成员身份。"""

        if not isinstance(member, TeamMember):
            raise TypeError("Team 成员仓储只能保存 TeamMember 对象。")
        path = self._path_for(member.team_id, member.member_id)
        if not path.exists():
            raise TeamEntityNotFoundError(entity_name="Team 成员", entity_id=member.member_id)
        write_json_atomically(path, encode_member(member))
        return member

    def _path_for(self, team_id: str, member_id: str) -> Path:
        return (
            self._root_directory
            / require_safe_identifier("team_id", team_id)
            / "members"
            / f"{require_safe_identifier('member_id', member_id)}.json"
        )

    @staticmethod
    def _read_member(path: Path, *, expected_member_id: str) -> TeamMember:
        try:
            member = decode_member(read_json_object(path))
            if member.member_id != expected_member_id:
                raise ValueError("Team 成员文件标识不匹配。")
            return member
        except (OSError, ValueError) as error:
            raise CorruptedTeamFileError(path=path) from error
