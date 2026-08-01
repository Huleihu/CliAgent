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


class TeamProtocolStateAlreadyExistsError(TeamDomainError):
    """同一协议请求标识已被持久化时抛出。"""

    def __init__(self, *, request_id: str) -> None:
        super().__init__(f"Team 协议请求“{request_id}”已存在。")
        self.request_id = request_id


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


class TeamProtocolError(TeamDomainError):
    """Team 结构化协议校验和匹配失败的共同基类。"""


class UnknownTeamProtocolRequestError(TeamProtocolError):
    """响应引用的协议请求不存在时抛出。"""

    def __init__(self, *, request_id: str) -> None:
        super().__init__(f"Team 协议请求“{request_id}”不存在。")
        self.request_id = request_id


class TeamProtocolRequestIdMismatchError(TeamProtocolError):
    """协议消息携带的 request_id 与状态不一致时抛出。"""

    def __init__(self, *, expected_request_id: str, actual_request_id: str) -> None:
        super().__init__(
            "Team 协议消息的 request_id 不匹配："
            f"期望“{expected_request_id}”，实际“{actual_request_id}”。"
        )
        self.expected_request_id = expected_request_id
        self.actual_request_id = actual_request_id


class TeamProtocolMessageTypeMismatchError(TeamProtocolError):
    """协议消息类型与请求所处协议不一致时抛出。"""

    def __init__(
        self,
        *,
        request_id: str,
        expected_message_type: str,
        actual_message_type: str,
    ) -> None:
        super().__init__(
            f"Team 协议请求“{request_id}”期望消息类型“{expected_message_type}”，"
            f"实际收到“{actual_message_type}”。"
        )
        self.request_id = request_id
        self.expected_message_type = expected_message_type
        self.actual_message_type = actual_message_type


class TeamProtocolParticipantMismatchError(TeamProtocolError):
    """协议消息发送方或接收方与原请求关系不一致时抛出。"""

    def __init__(self, *, request_id: str) -> None:
        super().__init__(f"Team 协议请求“{request_id}”的消息参与方不匹配。")
        self.request_id = request_id


class TeamProtocolPayloadMismatchError(TeamProtocolError):
    """请求消息正文与已登记协议载荷不一致时抛出。"""

    def __init__(self, *, request_id: str) -> None:
        super().__init__(f"Team 协议请求“{request_id}”的消息正文与登记载荷不匹配。")
        self.request_id = request_id


class TeamProtocolRequestConflictError(TeamProtocolError):
    """同一 request_id 试图表达不同请求事实时抛出。"""

    def __init__(self, *, request_id: str) -> None:
        super().__init__(f"Team 协议请求“{request_id}”已对应不同请求内容。")
        self.request_id = request_id


class TeamProtocolAlreadyResolvedError(TeamProtocolError):
    """已决请求收到不同响应时抛出，完全相同的重放仍保持幂等。"""

    def __init__(self, *, request_id: str, status: str) -> None:
        super().__init__(
            f"Team 协议请求“{request_id}”已处于“{status}”状态，不能接受不同响应。"
        )
        self.request_id = request_id
        self.status = status
