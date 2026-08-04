import pytest

from local_dev_agent.tasks import Task, TaskNotFoundError, TaskStatus
from local_dev_agent.teams import (
    TaskBoardTeamAutonomousWorkVerifier,
    TeamAutonomousWorkItem,
    TeamMember,
    TeamPromptExecution,
)


class FixedTaskReader:
    """为核验器提供可替换的当前 S12 快照。"""

    def __init__(self, task: Task | Exception) -> None:
        self._task = task
        self.task_ids: list[str] = []

    def get_task(self, task_id: str) -> Task:
        self.task_ids.append(task_id)
        if isinstance(self._task, Exception):
            raise self._task
        return self._task


def _member() -> TeamMember:
    return TeamMember.create(
        member_id="member-alice",
        team_id="team-001",
        name="alice",
        role="后端开发",
        session_id="session-alice",
    )


def _work_item() -> TeamAutonomousWorkItem:
    return TeamAutonomousWorkItem(
        task_id="task-api",
        subject="实现登录 API。",
        description="新增登录端点。",
    )


def _execution() -> TeamPromptExecution:
    return TeamPromptExecution(
        session_id="session-alice",
        run_id="run-001",
        response_text="接口和测试已完成。",
    )


def test_verifier_accepts_only_completed_task_owned_by_the_executing_member() -> None:
    reader = FixedTaskReader(
        Task(
            task_id="task-api",
            subject="实现登录 API。",
            description="新增登录端点。",
            status=TaskStatus.COMPLETED,
            owner="member-alice",
        )
    )

    outcome = TaskBoardTeamAutonomousWorkVerifier(
        task_reader=reader  # type: ignore[arg-type]
    ).verify(
        member=_member(),
        work_item=_work_item(),
        execution=_execution(),
    )

    assert reader.task_ids == ["task-api"]
    assert outcome.completed is True
    assert "接口和测试已完成。" in outcome.detail


@pytest.mark.parametrize(
    ("status", "owner"),
    (
        (TaskStatus.IN_PROGRESS, "member-alice"),
        (TaskStatus.COMPLETED, "member-other"),
    ),
)
def test_verifier_rejects_unfinished_or_wrong_owner_task(
    status: TaskStatus,
    owner: str,
) -> None:
    verifier = TaskBoardTeamAutonomousWorkVerifier(
        task_reader=FixedTaskReader(
            Task(
                task_id="task-api",
                subject="实现登录 API。",
                description="新增登录端点。",
                status=status,
                owner=owner,
            )
        )  # type: ignore[arg-type]
    )

    outcome = verifier.verify(
        member=_member(),
        work_item=_work_item(),
        execution=_execution(),
    )

    assert outcome.completed is False
    assert "未满足完成条件" in outcome.detail


def test_verifier_reports_failure_without_reading_task_when_run_did_not_finish() -> None:
    reader = FixedTaskReader(
        Task(
            task_id="task-api",
            subject="实现登录 API。",
            description="新增登录端点。",
            status=TaskStatus.COMPLETED,
            owner="member-alice",
        )
    )

    outcome = TaskBoardTeamAutonomousWorkVerifier(
        task_reader=reader  # type: ignore[arg-type]
    ).verify(
        member=_member(),
        work_item=_work_item(),
        execution=None,
    )

    assert outcome.completed is False
    assert reader.task_ids == []
    assert "未成功结束" in outcome.detail


def test_verifier_converts_a_missing_task_into_a_failed_outcome() -> None:
    verifier = TaskBoardTeamAutonomousWorkVerifier(
        task_reader=FixedTaskReader(TaskNotFoundError(task_id="task-api"))  # type: ignore[arg-type]
    )

    outcome = verifier.verify(
        member=_member(),
        work_item=_work_item(),
        execution=_execution(),
    )

    assert outcome.completed is False
    assert "任务快照不存在" in outcome.detail


def test_verifier_validates_its_task_reader_boundary() -> None:
    with pytest.raises(TypeError, match="task_reader 必须提供"):
        TaskBoardTeamAutonomousWorkVerifier(task_reader=object())  # type: ignore[arg-type]
