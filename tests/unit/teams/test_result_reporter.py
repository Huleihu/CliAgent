from datetime import datetime, timezone
from pathlib import Path

from local_dev_agent.teams import (
    InboxTeamResultReporter,
    JsonFileTeamInboxRepository,
    TeamMember,
    TeamMessageDraft,
    TeamMessageType,
    TeamPromptExecution,
)


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class FixedClock:
    """为结果消息提供可预测的持久化时间。"""

    def now(self) -> datetime:
        return TIMESTAMP


class RecordingDispatcher:
    """记录结果消息写入后被唤醒的接收者。"""

    def __init__(self) -> None:
        self.member_ids: list[str] = []

    def signal(self, *, member_id: str) -> None:
        self.member_ids.append(member_id)


def _member() -> TeamMember:
    return TeamMember.create(
        member_id="member-001",
        team_id="team-001",
        name="alice",
        role="后端开发",
        session_id="session-alice",
        created_at=TIMESTAMP,
    )


def _assignment() -> TeamMessageDraft:
    return TeamMessageDraft.create(
        message_id="assignment-message-001",
        team_id="team-001",
        sender_member_id="lead-001",
        recipient_member_id="member-001",
        message_type=TeamMessageType.ASSIGNMENT,
        content="检查数据库迁移。",
        idempotency_key="assignment-001",
        created_at=TIMESTAMP,
    )


def test_result_reporter_persists_idempotent_result_for_assignment_sender(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    source_message = inbox.send(_assignment())
    dispatcher = RecordingDispatcher()
    reporter = InboxTeamResultReporter(
        inbox_repository=inbox,
        clock=FixedClock(),
        dispatcher=dispatcher,
    )
    execution = TeamPromptExecution(
        session_id="session-alice",
        run_id="run-001",
        response_text="迁移检查完成。",
    )

    first = reporter.report(
        member=_member(),
        source_messages=(source_message,),
        execution=execution,
    )
    repeated = reporter.report(
        member=_member(),
        source_messages=(source_message,),
        execution=execution,
    )

    assert first == repeated
    assert dispatcher.member_ids == ["lead-001", "lead-001"]
    reports = inbox.list_unread(team_id="team-001", recipient_member_id="lead-001")
    assert len(reports) == 1
    assert reports[0].message_type is TeamMessageType.RESULT
    assert reports[0].content == (
        "[Team 执行结果]\n"
        "成员：member-001\n"
        "Run：run-001\n"
        "来源任务消息：assignment-message-001\n\n"
        "迁移检查完成。"
    )


def test_result_reporter_ignores_plain_messages(tmp_path: Path) -> None:
    inbox = JsonFileTeamInboxRepository(tmp_path)
    source_message = inbox.send(
        TeamMessageDraft.create(
            message_id="message-001",
            team_id="team-001",
            sender_member_id="member-002",
            recipient_member_id="member-001",
            message_type=TeamMessageType.PLAIN,
            content="请同步进度。",
            idempotency_key="message-001",
            created_at=TIMESTAMP,
        )
    )
    dispatcher = RecordingDispatcher()

    reports = InboxTeamResultReporter(
        inbox_repository=inbox,
        clock=FixedClock(),
        dispatcher=dispatcher,
    ).report(
        member=_member(),
        source_messages=(source_message,),
        execution=TeamPromptExecution(
            session_id="session-alice",
            run_id="run-001",
            response_text="已收到。",
        ),
    )

    assert reports == ()
    assert dispatcher.member_ids == []
