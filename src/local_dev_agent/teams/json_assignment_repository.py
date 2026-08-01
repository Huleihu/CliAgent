"""Team 工作分配的 JSON 文件仓储适配器。"""

from __future__ import annotations

from pathlib import Path

from .errors import (
    CorruptedTeamFileError,
    TeamAssignmentAlreadyExistsError,
    TeamEntityNotFoundError,
)
from .json_codec import decode_assignment, encode_assignment
from .json_support import read_json_object, require_safe_identifier, write_json_atomically
from .schema import TeamAssignment


class JsonFileTeamAssignmentRepository:
    """按 Team 目录、每项一个 JSON 文件保存工作分配快照。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("Team 工作分配仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory

    def add(self, assignment: TeamAssignment) -> TeamAssignment:
        """新增分配，拒绝跨 Team 复用同一标识。"""

        if not isinstance(assignment, TeamAssignment):
            raise TypeError("工作分配仓储只能保存 TeamAssignment 对象。")
        if self.get(assignment.assignment_id) is not None:
            raise TeamAssignmentAlreadyExistsError(assignment_id=assignment.assignment_id)
        write_json_atomically(
            self._path_for(assignment.team_id, assignment.assignment_id),
            encode_assignment(assignment),
        )
        return assignment

    def get(self, assignment_id: str) -> TeamAssignment | None:
        """在全部 Team 目录中按稳定路径查找分配。"""

        safe_assignment_id = require_safe_identifier("assignment_id", assignment_id)
        paths = tuple(
            sorted(self._root_directory.glob(f"*/assignments/{safe_assignment_id}.json"))
        )
        if not paths:
            return None
        if len(paths) > 1:
            raise CorruptedTeamFileError(path=self._root_directory)
        return self._read_assignment(paths[0], expected_assignment_id=safe_assignment_id)

    def list_for_team(self, team_id: str) -> tuple[TeamAssignment, ...]:
        """按文件名稳定返回一个 Team 的全部分配。"""

        directory = self._root_directory / require_safe_identifier("team_id", team_id) / "assignments"
        if not directory.exists():
            return ()
        return tuple(
            self._read_assignment(path, expected_assignment_id=path.stem)
            for path in sorted(directory.glob("*.json"))
        )

    def list_for_assignee(self, member_id: str) -> tuple[TeamAssignment, ...]:
        """扫描全部分配并以更新时间、标识稳定排序接收者工作。"""

        safe_member_id = require_safe_identifier("member_id", member_id)
        assignments = tuple(
            self._read_assignment(path, expected_assignment_id=path.stem)
            for path in sorted(self._root_directory.glob("*/assignments/*.json"))
        )
        return tuple(
            sorted(
                (
                    assignment
                    for assignment in assignments
                    if assignment.assignee_member_id == safe_member_id
                ),
                key=lambda assignment: (assignment.updated_at, assignment.assignment_id),
            )
        )

    def replace(self, assignment: TeamAssignment) -> TeamAssignment:
        """原子替换已有分配，不允许状态迁移意外新建记录。"""

        if not isinstance(assignment, TeamAssignment):
            raise TypeError("工作分配仓储只能保存 TeamAssignment 对象。")
        path = self._path_for(assignment.team_id, assignment.assignment_id)
        if not path.exists():
            raise TeamEntityNotFoundError(
                entity_name="Team 工作分配",
                entity_id=assignment.assignment_id,
            )
        write_json_atomically(path, encode_assignment(assignment))
        return assignment

    def _path_for(self, team_id: str, assignment_id: str) -> Path:
        return (
            self._root_directory
            / require_safe_identifier("team_id", team_id)
            / "assignments"
            / f"{require_safe_identifier('assignment_id', assignment_id)}.json"
        )

    @staticmethod
    def _read_assignment(path: Path, *, expected_assignment_id: str) -> TeamAssignment:
        try:
            assignment = decode_assignment(read_json_object(path))
            if assignment.assignment_id != expected_assignment_id:
                raise ValueError("工作分配文件标识不匹配。")
            return assignment
        except (OSError, ValueError) as error:
            raise CorruptedTeamFileError(path=path) from error
