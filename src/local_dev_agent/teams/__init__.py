"""S15 Team 协作的领域契约与可替换端口。"""

from .ports import (
    TeamAgentExecutor,
    TeamAssignmentRepository,
    TeamClock,
    TeamDispatcher,
    TeamIdGenerator,
    TeamInboxRepository,
    TeamMemberRepository,
    TeamRepository,
)
from .schema import (
    InboxReservation,
    Team,
    TeamAssignment,
    TeamAssignmentStatus,
    TeamMember,
    TeamMemberStatus,
    TeamMessage,
    TeamMessageDeliveryStatus,
    TeamMessageType,
    TeamPromptExecution,
    TeamStatus,
)

__all__ = [
    "InboxReservation",
    "Team",
    "TeamAgentExecutor",
    "TeamAssignment",
    "TeamAssignmentRepository",
    "TeamAssignmentStatus",
    "TeamClock",
    "TeamDispatcher",
    "TeamIdGenerator",
    "TeamInboxRepository",
    "TeamMember",
    "TeamMemberRepository",
    "TeamMemberStatus",
    "TeamMessage",
    "TeamMessageDeliveryStatus",
    "TeamMessageType",
    "TeamPromptExecution",
    "TeamRepository",
    "TeamStatus",
]
