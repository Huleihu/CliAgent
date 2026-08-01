"""S15 Team 协作的领域契约、持久化适配器与应用服务。"""

from .clock import SystemTeamClock
from .identifiers import UuidTeamIdGenerator
from .json_assignment_repository import JsonFileTeamAssignmentRepository
from .json_inbox_repository import JsonFileTeamInboxRepository
from .json_team_repository import JsonFileTeamMemberRepository, JsonFileTeamRepository
from .ports import (
    TeamAgentExecutor,
    TeamAssignmentRepository,
    TeamClock,
    TeamDispatcher,
    TeamExecutionGate,
    TeamIdGenerator,
    TeamInboxRepository,
    TeamMemberRepository,
    TeamRepository,
    TeamResultReporter,
    TeamSignalRegistry,
    TeamThreadFactory,
    TeamWaiter,
)
from .lead_runner import TeamLeadInboxRunner
from .result_reporter import InboxTeamResultReporter
from .runner import TeamMemberRunner
from .runtime_adapter import RuntimeTeamAgentExecutor
from .schema import (
    InboxReservation,
    Team,
    TeamAssignment,
    TeamAssignmentStatus,
    TeamMember,
    TeamMemberStatus,
    TeamMessage,
    TeamMessageDraft,
    TeamMessageDeliveryStatus,
    TeamMessageType,
    TeamPromptExecution,
    TeamStatus,
)
from .service import TeamRecoveryResult, TeamService
from .threading import DaemonTeamThreadFactory, EventTeamDispatcher, EventTeamWaiter

__all__ = [
    "InboxReservation",
    "InboxTeamResultReporter",
    "DaemonTeamThreadFactory",
    "EventTeamDispatcher",
    "EventTeamWaiter",
    "JsonFileTeamAssignmentRepository",
    "JsonFileTeamInboxRepository",
    "JsonFileTeamMemberRepository",
    "JsonFileTeamRepository",
    "SystemTeamClock",
    "Team",
    "TeamAgentExecutor",
    "TeamAssignment",
    "TeamAssignmentRepository",
    "TeamAssignmentStatus",
    "TeamClock",
    "TeamDispatcher",
    "TeamExecutionGate",
    "TeamIdGenerator",
    "TeamInboxRepository",
    "TeamMember",
    "TeamLeadInboxRunner",
    "TeamMemberRepository",
    "TeamMemberStatus",
    "TeamMessage",
    "TeamMessageDraft",
    "TeamMessageDeliveryStatus",
    "TeamMessageType",
    "TeamPromptExecution",
    "TeamRepository",
    "TeamResultReporter",
    "TeamRecoveryResult",
    "RuntimeTeamAgentExecutor",
    "TeamMemberRunner",
    "TeamSignalRegistry",
    "TeamService",
    "TeamStatus",
    "TeamThreadFactory",
    "TeamWaiter",
    "UuidTeamIdGenerator",
]
