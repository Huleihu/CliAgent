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


class TeamAlreadyExistsError(TeamDomainError):
    """同一 Team 标识已被持久化时抛出。"""

    def __init__(self, *, team_id: str) -> None:
        super().__init__(f"Team“{team_id}”已存在。")
        self.team_id = team_id


class TeamMemberAlreadyExistsError(TeamDomainError):
    """同一成员标识已被持久化时抛出。"""

    def __init__(self, *, member_id: str) -> None:
        super().__init__(f"Team 成员“{member_id}”已存在。")
        self.member_id = member_id


class TeamAssignmentAlreadyExistsError(TeamDomainError):
    """同一工作分配标识已被持久化时抛出。"""

    def __init__(self, *, assignment_id: str) -> None:
        super().__init__(f"Team 工作分配“{assignment_id}”已存在。")
        self.assignment_id = assignment_id


class TeamEntityNotFoundError(TeamDomainError):
    """要求替换的 Team 实体不存在时抛出。"""

    def __init__(self, *, entity_name: str, entity_id: str) -> None:
        super().__init__(f"{entity_name}“{entity_id}”不存在。")
        self.entity_name = entity_name
        self.entity_id = entity_id


class CorruptedTeamFileError(TeamDomainError):
    """Team JSON 文件无法安全恢复时抛出。"""

    def __init__(self, *, path: object) -> None:
        super().__init__(f"Team 状态文件已损坏或格式不兼容：{path}。")
        self.path = path


class TeamMessageIdempotencyConflictError(TeamDomainError):
    """相同幂等键试图表达不同消息时抛出。"""

    def __init__(self, *, idempotency_key: str) -> None:
        super().__init__(f"消息幂等键“{idempotency_key}”已对应不同投递内容。")
        self.idempotency_key = idempotency_key
