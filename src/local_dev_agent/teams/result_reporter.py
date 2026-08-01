"""将成员执行结论持久化为 Team RESULT 消息的适配器。"""

from __future__ import annotations

from collections.abc import Sequence

from .ports import TeamClock, TeamDispatcher, TeamInboxRepository, TeamResultReporter
from .protocol_types import TeamMessageType
from .schema import TeamMember, TeamMessage, TeamMessageDraft, TeamPromptExecution


class InboxTeamResultReporter(TeamResultReporter):
    """按派活消息的发送者投递结果，并在写入后唤醒接收方。"""

    def __init__(
        self,
        *,
        inbox_repository: TeamInboxRepository,
        clock: TeamClock,
        dispatcher: TeamDispatcher,
    ) -> None:
        if not callable(getattr(inbox_repository, "send", None)):
            raise TypeError("inbox_repository 必须提供 send 方法。")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须提供 now 方法。")
        if not callable(getattr(dispatcher, "signal", None)):
            raise TypeError("dispatcher 必须提供 signal 方法。")
        self._inbox_repository = inbox_repository
        self._clock = clock
        self._dispatcher = dispatcher

    def report(
        self,
        *,
        member: TeamMember,
        source_messages: Sequence[TeamMessage],
        execution: TeamPromptExecution,
    ) -> tuple[TeamMessage, ...]:
        """仅为 ASSIGNMENT 回传最终文本，普通消息仍由成员显式回复。"""

        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        if not isinstance(execution, TeamPromptExecution):
            raise TypeError("execution 必须是 TeamPromptExecution 对象。")
        assignments_by_sender: dict[str, list[TeamMessage]] = {}
        for message in source_messages:
            if not isinstance(message, TeamMessage):
                raise TypeError("source_messages 必须只包含 TeamMessage 对象。")
            if message.message_type is TeamMessageType.ASSIGNMENT:
                assignments_by_sender.setdefault(message.sender_member_id, []).append(message)

        reports: list[TeamMessage] = []
        for recipient_member_id, messages in assignments_by_sender.items():
            source_message_ids = tuple(message.message_id for message in messages)
            report = self._inbox_repository.send(
                TeamMessageDraft.create(
                    message_id=(
                        f"result-message-{execution.run_id}-{recipient_member_id}"
                    ),
                    team_id=member.team_id,
                    sender_member_id=member.member_id,
                    recipient_member_id=recipient_member_id,
                    message_type=TeamMessageType.RESULT,
                    content=_format_result_content(
                        member=member,
                        execution=execution,
                        source_message_ids=source_message_ids,
                    ),
                    idempotency_key=(
                        f"result:{member.member_id}:{execution.run_id}:{recipient_member_id}"
                    ),
                    created_at=self._clock.now(),
                )
            )
            self._dispatcher.signal(member_id=recipient_member_id)
            reports.append(report)
        return tuple(reports)


def _format_result_content(
    *,
    member: TeamMember,
    execution: TeamPromptExecution,
    source_message_ids: tuple[str, ...],
) -> str:
    """保留追溯字段，避免 Lead 只能从自由文本猜测结果来源。"""

    return "\n".join(
        (
            "[Team 执行结果]",
            f"成员：{member.member_id}",
            f"Run：{execution.run_id}",
            f"来源任务消息：{', '.join(source_message_ids)}",
            "",
            execution.response_text,
        )
    )
