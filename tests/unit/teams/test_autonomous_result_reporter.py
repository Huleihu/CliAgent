from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_dev_agent.teams import (
    InboxTeamAutonomousResultReporter,
    JsonFileTeamInboxRepository,
    Team,
    TeamAutonomousWorkItem,
    TeamAutonomousWorkOutcome,
    TeamMember,
    TeamPromptExecution,
)


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self) -> datetime:
        return TIMESTAMP


class FixedTeamRepository:
    def __init__(self, team: Team | None) -> None:
        self._team = team

    def get(self, team_id: str) -> Team | None:
        if self._team is None or self._team.team_id != team_id:
            return None
        return self._team


class RecordingDispatcher:
    def __init__(self) -> None:
        self.member_ids: list[str] = []

    def signal(self, *, member_id: str) -> None:
        self.member_ids.append(member_id)


def _team() -> Team:
    return Team.create(
        team_id="team-001",
        workspace_id="workspace-001",
        lead_member_id="member-lead",
        created_at=TIMESTAMP,
    )


def _member(member_id: str = "member-alice") -> TeamMember:
    return TeamMember.create(
        member_id=member_id,
        team_id="team-001",
        name="alice",
        role="后端开发",
        session_id="session-alice",
        created_at=TIMESTAMP,
    )


def _outcome(*, completed: bool, execution: TeamPromptExecution | None) -> TeamAutonomousWorkOutcome:
    return TeamAutonomousWorkOutcome(
        work_item=TeamAutonomousWorkItem(
            task_id="task-api",
            subject="实现登录 API。",
            description="新增登录端点。",
        ),
        execution=execution,
        completed=completed,
        detail="任务状态已核验。" if completed else "任务尚未完成。",
    )


def test_reporter_persists_one_idempotent_result_for_the_team_lead(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    dispatcher = RecordingDispatcher()
    reporter = InboxTeamAutonomousResultReporter(
        team_repository=FixedTeamRepository(_team()),  # type: ignore[arg-type]
        inbox_repository=inbox,
        clock=FixedClock(),
        dispatcher=dispatcher,
    )
    outcome = _outcome(
        completed=True,
        execution=TeamPromptExecution(
            session_id="session-alice",
            run_id="run-001",
            response_text="接口和测试已完成。",
        ),
    )

    first = reporter.report(member=_member(), outcome=outcome)
    repeated = reporter.report(member=_member(), outcome=outcome)

    assert first == repeated
    assert dispatcher.member_ids == ["member-lead", "member-lead"]
    reports = inbox.list_unread(team_id="team-001", recipient_member_id="member-lead")
    assert len(reports) == 1
    assert reports[0].content == (
        "[Team 自主任务结果]\n"
        "成员：member-alice\n"
        "任务：task-api\n"
        "标题：实现登录 API。\n"
        "Run：run-001\n"
        "核验：已完成\n\n"
        "任务状态已核验。"
    )


def test_reporter_keeps_failed_run_visible_without_faking_a_run_id(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    report = InboxTeamAutonomousResultReporter(
        team_repository=FixedTeamRepository(_team()),  # type: ignore[arg-type]
        inbox_repository=inbox,
        clock=FixedClock(),
        dispatcher=RecordingDispatcher(),
    ).report(
        member=_member(),
        outcome=_outcome(completed=False, execution=None),
    )

    assert "Run：（未创建）" in report.content
    assert "核验：未完成" in report.content


def test_reporter_rejects_missing_team_or_a_member_reporting_to_itself(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    outcome = _outcome(completed=False, execution=None)
    missing_team_reporter = InboxTeamAutonomousResultReporter(
        team_repository=FixedTeamRepository(None),  # type: ignore[arg-type]
        inbox_repository=inbox,
        clock=FixedClock(),
        dispatcher=RecordingDispatcher(),
    )
    with pytest.raises(ValueError, match="无法找到所属 Team"):
        missing_team_reporter.report(member=_member(), outcome=outcome)

    lead_reporter = InboxTeamAutonomousResultReporter(
        team_repository=FixedTeamRepository(_team()),  # type: ignore[arg-type]
        inbox_repository=inbox,
        clock=FixedClock(),
        dispatcher=RecordingDispatcher(),
    )
    with pytest.raises(ValueError, match="不能向自身回传"):
        lead_reporter.report(member=_member("member-lead"), outcome=outcome)
