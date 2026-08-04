"""将经核验的自主工作结论持久化为发给 Team Lead 的 RESULT。"""

from .ports import (
    TeamAutonomousResultReporter,
    TeamClock,
    TeamDispatcher,
    TeamInboxRepository,
    TeamRepository,
)
from .protocol_types import TeamMessageType
from .schema import TeamAutonomousWorkOutcome, TeamMember, TeamMessage, TeamMessageDraft


class InboxTeamAutonomousResultReporter(TeamAutonomousResultReporter):
    """以稳定任务和 Run 标识幂等回传自主工作核验结论。"""

    def __init__(
        self,
        *,
        team_repository: TeamRepository,
        inbox_repository: TeamInboxRepository,
        clock: TeamClock,
        dispatcher: TeamDispatcher,
    ) -> None:
        if not callable(getattr(team_repository, "get", None)):
            raise TypeError("team_repository 必须提供 get 方法。")
        if not callable(getattr(inbox_repository, "send", None)):
            raise TypeError("inbox_repository 必须提供 send 方法。")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须提供 now 方法。")
        if not callable(getattr(dispatcher, "signal", None)):
            raise TypeError("dispatcher 必须提供 signal 方法。")
        self._team_repository = team_repository
        self._inbox_repository = inbox_repository
        self._clock = clock
        self._dispatcher = dispatcher

    def report(
        self,
        *,
        member: TeamMember,
        outcome: TeamAutonomousWorkOutcome,
    ) -> TeamMessage:
        """向当前 Team Lead 写入一条 RESULT；同一任务 Run 重试时复用消息标识。"""

        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        if not isinstance(outcome, TeamAutonomousWorkOutcome):
            raise TypeError("outcome 必须是 TeamAutonomousWorkOutcome 对象。")
        team = self._team_repository.get(member.team_id)
        if team is None:
            raise ValueError("自主任务结果无法找到所属 Team。")
        if member.member_id == team.lead_member_id:
            raise ValueError("自主任务成员不能向自身回传结果。")
        run_id = outcome.execution.run_id if outcome.execution is not None else "no-run"
        task_id = outcome.work_item.task_id
        lead_member_id = team.lead_member_id
        report = self._inbox_repository.send(
            TeamMessageDraft.create(
                message_id=(
                    f"autonomous-result-{member.member_id}-{task_id}-{run_id}"
                ),
                team_id=member.team_id,
                sender_member_id=member.member_id,
                recipient_member_id=lead_member_id,
                message_type=TeamMessageType.RESULT,
                content=_format_autonomous_result_content(member=member, outcome=outcome),
                idempotency_key=(
                    f"autonomous-result:{member.member_id}:{task_id}:{run_id}"
                ),
                created_at=self._clock.now(),
            )
        )
        self._dispatcher.signal(member_id=lead_member_id)
        return report


def _format_autonomous_result_content(
    *,
    member: TeamMember,
    outcome: TeamAutonomousWorkOutcome,
) -> str:
    """让 Lead 无需解析自由文本即可了解任务、Run 和核验结论。"""

    run_id = outcome.execution.run_id if outcome.execution is not None else "（未创建）"
    verdict = "已完成" if outcome.completed else "未完成"
    return "\n".join(
        (
            "[Team 自主任务结果]",
            f"成员：{member.member_id}",
            f"任务：{outcome.work_item.task_id}",
            f"标题：{outcome.work_item.subject}",
            f"Run：{run_id}",
            f"核验：{verdict}",
            "",
            outcome.detail,
        )
    )
