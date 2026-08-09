import pytest

from local_dev_agent.tasks import Task, TaskStatus
from local_dev_agent.teams import TaskBoardTeamAutonomousWorkSource, TeamMember


class RecordingTaskBoard:
    """记录适配器传入的成员标识，不绑定 TaskService 具体实现。"""

    def __init__(self, task: Task | None) -> None:
        self._task = task
        self.owners: list[str] = []

    def claim_next_task(self, *, owner: str) -> Task | None:
        self.owners.append(owner)
        return self._task


def _member() -> TeamMember:
    return TeamMember.create(
        member_id="member-alice",
        team_id="team-001",
        name="alice",
        role="后端开发",
        session_id="session-alice",
    )


def test_work_source_claims_a_task_with_member_identity_and_converts_it() -> None:
    task_board = RecordingTaskBoard(
        Task(
            task_id="task-api",
            subject="实现登录 API。",
            description="新增登录端点并覆盖失败场景。",
            status=TaskStatus.PENDING,
            owner=None,
            worktree="api-login",
        )
    )
    source = TaskBoardTeamAutonomousWorkSource(task_board=task_board)  # type: ignore[arg-type]

    work_item = source.claim_next_work(member=_member())

    assert task_board.owners == ["member-alice"]
    assert work_item is not None
    assert work_item.task_id == "task-api"
    assert work_item.subject == "实现登录 API。"
    assert work_item.description == "新增登录端点并覆盖失败场景。"
    assert work_item.worktree == "api-login"


def test_work_source_returns_none_when_the_task_board_has_no_claimable_task() -> None:
    task_board = RecordingTaskBoard(None)
    source = TaskBoardTeamAutonomousWorkSource(task_board=task_board)  # type: ignore[arg-type]

    assert source.claim_next_work(member=_member()) is None


def test_work_source_validates_its_task_board_and_member_boundary() -> None:
    with pytest.raises(TypeError, match="task_board 必须提供"):
        TaskBoardTeamAutonomousWorkSource(task_board=object())  # type: ignore[arg-type]

    source = TaskBoardTeamAutonomousWorkSource(
        task_board=RecordingTaskBoard(None)  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError, match="member 必须是"):
        source.claim_next_work(member=object())  # type: ignore[arg-type]
