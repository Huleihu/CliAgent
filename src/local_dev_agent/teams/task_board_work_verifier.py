"""根据 S12 任务快照核验成员自主工作的完成事实。"""

from local_dev_agent.tasks import Task, TaskNotFoundError, TaskSnapshotReader, TaskStatus

from .ports import TeamAutonomousWorkVerifier
from .schema import (
    TeamAutonomousWorkItem,
    TeamAutonomousWorkOutcome,
    TeamMember,
    TeamPromptExecution,
)


class TaskBoardTeamAutonomousWorkVerifier(TeamAutonomousWorkVerifier):
    """只接受 S12 的 completed/owner 事实，不从模型响应文本推断任务完成。"""

    def __init__(self, *, task_reader: TaskSnapshotReader) -> None:
        if not callable(getattr(task_reader, "get_task", None)):
            raise TypeError("task_reader 必须提供 get_task 方法。")
        self._task_reader = task_reader

    def verify(
        self,
        *,
        member: TeamMember,
        work_item: TeamAutonomousWorkItem,
        execution: TeamPromptExecution | None,
    ) -> TeamAutonomousWorkOutcome:
        """读取最新任务快照，仅在同一成员完成任务且 Run 正常结束时报告成功。"""

        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        if not isinstance(work_item, TeamAutonomousWorkItem):
            raise TypeError("work_item 必须是 TeamAutonomousWorkItem 对象。")
        if execution is not None and not isinstance(execution, TeamPromptExecution):
            raise TypeError("execution 必须是 TeamPromptExecution 对象或空值。")
        if execution is None:
            return TeamAutonomousWorkOutcome(
                work_item=work_item,
                execution=None,
                completed=False,
                detail="成员 Run 未成功结束，无法确认任务已完成。",
            )

        try:
            task = self._task_reader.get_task(work_item.task_id)
        except TaskNotFoundError:
            return TeamAutonomousWorkOutcome(
                work_item=work_item,
                execution=execution,
                completed=False,
                detail="任务快照不存在，无法确认任务已完成。",
            )
        if not isinstance(task, Task):
            raise TypeError("task_reader 必须返回 Task 对象。")
        if task.status is TaskStatus.COMPLETED and task.owner == member.member_id:
            return TeamAutonomousWorkOutcome(
                work_item=work_item,
                execution=execution,
                completed=True,
                detail="任务状态已核验为 completed。\n\n成员执行摘要：\n"
                f"{execution.response_text}",
            )
        owner = task.owner if task.owner is not None else "（未认领）"
        return TeamAutonomousWorkOutcome(
            work_item=work_item,
            execution=execution,
            completed=False,
            detail=(
                "任务尚未满足完成条件："
                f"status={task.status.value}，owner={owner}。"
            ),
        )
