"""Team 领域可由调用方稳定识别的错误类型。"""


class TeamDomainError(ValueError):
    """所有 Team 领域校验和状态错误的共同基类。"""


class InvalidTeamAssignmentTransitionError(TeamDomainError):
    """工作分配不能按当前状态迁移时抛出。"""

    def __init__(
        self,
        *,
        assignment_id: str,
        status: str,
        target_status: str,
    ) -> None:
        super().__init__(
            f"工作分配“{assignment_id}”当前状态为“{status}”，不能迁移到“{target_status}”。"
        )
        self.assignment_id = assignment_id
        self.status = status
        self.target_status = target_status


class InvalidTeamMessageTransitionError(TeamDomainError):
    """消息预留、释放或确认消费的关联不匹配时抛出。"""

    def __init__(
        self,
        *,
        message_id: str,
        status: str,
        action: str,
    ) -> None:
        super().__init__(
            f"消息“{message_id}”当前状态为“{status}”，不能执行“{action}”。"
        )
        self.message_id = message_id
        self.status = status
        self.action = action
