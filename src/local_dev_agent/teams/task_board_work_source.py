"""将 S12 自主任务板适配为 Team 成员的自主工作来源。"""

from local_dev_agent.tasks import AutonomousTaskBoard

from .ports import TeamAutonomousWorkSource
from .schema import TeamAutonomousWorkItem, TeamMember


class TaskBoardTeamAutonomousWorkSource(TeamAutonomousWorkSource):
    """仅通过 S12 自主任务板为成员认领项目任务，不了解 Team Runner。"""

    def __init__(self, *, task_board: AutonomousTaskBoard) -> None:
        if not callable(getattr(task_board, "claim_next_task", None)):
            raise TypeError("task_board 必须提供 claim_next_task 方法。")
        self._task_board = task_board

    def claim_next_work(self, *, member: TeamMember) -> TeamAutonomousWorkItem | None:
        """以 Team 成员标识认领 S12 任务，并转换为独立的 Team 工作项。"""

        if not isinstance(member, TeamMember):
            raise TypeError("member 必须是 TeamMember 对象。")
        task = self._task_board.claim_next_task(owner=member.member_id)
        if task is None:
            return None
        return TeamAutonomousWorkItem(
            task_id=task.task_id,
            subject=task.subject,
            description=task.description,
        )
