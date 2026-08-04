"""S15 Team 协作的领域契约、持久化适配器与应用服务。"""

from .clock import SystemTeamClock
from .identifiers import UuidTeamIdGenerator
from .json_assignment_repository import JsonFileTeamAssignmentRepository
from .json_inbox_repository import JsonFileTeamInboxRepository
from .json_protocol_state_repository import JsonFileTeamProtocolStateRepository
from .json_team_repository import JsonFileTeamMemberRepository, JsonFileTeamRepository
from .ports import (
    TeamAgentExecutor,
    TeamAutonomousResultReporter,
    TeamAutonomousWorkSource,
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
    TeamProtocolStateRepository,
    TeamProtocolRequestSender,
    TeamShutdownRequester,
    TeamProtocolMessageDispatcher,
)
from .lead_runner import TeamLeadInboxRunner
from .protocol_dispatch import (
    TeamProtocolCoordinator,
    TeamProtocolDispatchDisposition,
    TeamProtocolDispatchResult,
)
from .protocol_state import TeamProtocolState
from .protocol_routing import TeamProtocolBatchRoute, TeamProtocolInboxRouter
from .protocol_types import (
    TeamMessageType,
    TeamProtocolDecision,
    TeamProtocolStatus,
    TeamProtocolType,
)
from .result_reporter import InboxTeamResultReporter
from .runner import TeamMemberRunner
from .runtime_adapter import RuntimeTeamAgentExecutor
from .task_board_work_source import TaskBoardTeamAutonomousWorkSource
from .schema import (
    InboxReservation,
    Team,
    TeamAutonomousWorkItem,
    TeamAutonomousWorkOutcome,
    TeamAssignment,
    TeamAssignmentStatus,
    TeamMember,
    TeamMemberStatus,
    TeamMessage,
    TeamMessageDraft,
    TeamMessageDeliveryStatus,
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
    "JsonFileTeamProtocolStateRepository",
    "JsonFileTeamMemberRepository",
    "JsonFileTeamRepository",
    "SystemTeamClock",
    "Team",
    "TeamAgentExecutor",
    "TeamAutonomousResultReporter",
    "TeamAutonomousWorkItem",
    "TeamAutonomousWorkOutcome",
    "TeamAutonomousWorkSource",
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
    "TeamProtocolCoordinator",
    "TeamProtocolBatchRoute",
    "TeamProtocolDecision",
    "TeamProtocolDispatchDisposition",
    "TeamProtocolDispatchResult",
    "TeamProtocolInboxRouter",
    "TeamProtocolMessageDispatcher",
    "TeamProtocolState",
    "TeamProtocolStateRepository",
    "TeamProtocolRequestSender",
    "TeamProtocolStatus",
    "TeamProtocolType",
    "TeamRepository",
    "TeamResultReporter",
    "TeamRecoveryResult",
    "RuntimeTeamAgentExecutor",
    "TeamMemberRunner",
    "TeamSignalRegistry",
    "TeamService",
    "TeamShutdownRequester",
    "TeamStatus",
    "TeamThreadFactory",
    "TaskBoardTeamAutonomousWorkSource",
    "TeamWaiter",
    "UuidTeamIdGenerator",
]
