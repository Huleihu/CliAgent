from datetime import datetime, timezone

import pytest

from local_dev_agent.teams import (
    Team,
    TeamAssignment,
    TeamMember,
    TeamMessage,
    TeamMessageType,
)
from local_dev_agent.tools import (
    ToolCallRequest,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)
from local_dev_agent.tools.builtin import (
    AddTeammateTool,
    AssignTeamWorkTool,
    CreateTeamTool,
    SendTeamMessageTool,
)
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


TIMESTAMP = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


class RecordingTeamService:
    """用稳定快照观察工具是否只把上下文和参数交给应用服务。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def create_team(self, **kwargs: object) -> tuple[Team, TeamMember]:
        self.calls.append(("create_team", kwargs))
        lead = TeamMember.create(
            member_id="lead-001",
            team_id="team-001",
            name=str(kwargs["lead_name"]),
            role=str(kwargs["lead_role"]),
            session_id=str(kwargs["lead_session_id"]),
            created_at=TIMESTAMP,
        )
        return (
            Team.create(
                team_id="team-001",
                workspace_id=str(kwargs["workspace_id"]),
                lead_member_id=lead.member_id,
                created_at=TIMESTAMP,
            ),
            lead,
        )

    def add_teammate(self, **kwargs: object) -> TeamMember:
        self.calls.append(("add_teammate", kwargs))
        return TeamMember.create(
            member_id="member-001",
            team_id=str(kwargs["team_id"]),
            name=str(kwargs["name"]),
            role=str(kwargs["role"]),
            session_id=str(kwargs["session_id"]),
            created_at=TIMESTAMP,
        )

    def assign_work(self, **kwargs: object) -> TeamAssignment:
        self.calls.append(("assign_work", kwargs))
        return TeamAssignment.create(
            assignment_id=str(kwargs["assignment_id"]),
            team_id=str(kwargs["team_id"]),
            assigned_by_member_id=str(kwargs["assigned_by_member_id"]),
            assignee_member_id=str(kwargs["assignee_member_id"]),
            prompt=str(kwargs["prompt"]),
            project_task_id=kwargs["project_task_id"],  # type: ignore[arg-type]
            created_at=TIMESTAMP,
        )

    def send_message(self, **kwargs: object) -> TeamMessage:
        self.calls.append(("send_message", kwargs))
        return TeamMessage.create(
            message_id=str(kwargs["message_id"]),
            team_id=str(kwargs["team_id"]),
            sender_member_id=str(kwargs["sender_member_id"]),
            recipient_member_id=str(kwargs["recipient_member_id"]),
            sequence=1,
            message_type=TeamMessageType.PLAIN,
            content=str(kwargs["content"]),
            idempotency_key=str(kwargs["idempotency_key"]),
            created_at=TIMESTAMP,
        )


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="session-lead",
        run_id="run-001",
        step_id="step-001",
        call_id="call-001",
    )


def test_team_tools_use_stable_parent_visible_names() -> None:
    service = RecordingTeamService()

    assert tuple(
        tool.definition.name
        for tool in (
            CreateTeamTool(service),
            AddTeammateTool(service),
            AssignTeamWorkTool(service),
            SendTeamMessageTool(service),
        )
    ) == (
        "create_team",
        "add_teammate",
        "assign_team_work",
        "send_team_message",
    )


def test_team_tools_bind_member_actions_to_execution_context_and_stable_call_identity() -> None:
    service = RecordingTeamService()
    create = CreateTeamTool(service)
    add = AddTeammateTool(service)
    assign = AssignTeamWorkTool(service)
    send = SendTeamMessageTool(service)
    context = _context()

    created = create.run(
        {
            "workspace_id": "workspace-001",
            "lead_name": "lead",
            "lead_role": "协调者",
        },
        context=context,
    )
    member = add.run(
        {
            "team_id": "team-001",
            "lead_member_id": "lead-001",
            "name": "alice",
            "role": "后端开发",
            "session_id": "session-alice",
        },
        context=context,
    )
    assignment = assign.run(
        {
            "team_id": "team-001",
            "lead_member_id": "lead-001",
            "assignee_member_id": "member-001",
            "prompt": "检查数据库迁移。",
            "project_task_id": "project-task-001",
        },
        context=context,
    )
    message = send.run(
        {
            "team_id": "team-001",
            "sender_member_id": "lead-001",
            "recipient_member_id": "member-001",
            "content": "迁移环境已准备好。",
        },
        context=context,
    )

    assert created["lead"]["session_id"] == "session-lead"  # type: ignore[index]
    assert member["session_id"] == "session-alice"
    assert assignment["assignment_id"] == "assignment-call-001"
    assert message["message_id"] == "message-call-001"
    assert service.calls[1][1]["lead_session_id"] == "session-lead"
    assert service.calls[2][1]["assigned_by_session_id"] == "session-lead"
    assert service.calls[3][1]["idempotency_key"] == "team-message-call-001"


def test_team_tools_use_standard_executor_validation_and_require_context() -> None:
    service = RecordingTeamService()
    registry = ToolRegistry()
    registry.register(CreateTeamTool(service))
    executor = ToolExecutor(registry)

    invalid = executor.execute(
        ToolCallRequest(
            name="create_team",
            arguments={
                "workspace_id": "workspace-001",
                "lead_name": "lead",
                "lead_role": "协调者",
                "unexpected": "value",
            },
        ),
        context=_context(),
    )
    missing_context = executor.execute(
        ToolCallRequest(
            name="create_team",
            arguments={
                "workspace_id": "workspace-001",
                "lead_name": "lead",
                "lead_role": "协调者",
            },
        )
    )

    assert invalid.success is False
    assert invalid.error is not None
    assert invalid.error["type"] == "ToolValidationError"
    assert missing_context.success is False
    assert missing_context.error is not None
    assert missing_context.error["type"] == "ToolExecutionError"
    with pytest.raises(ToolExecutionError, match="ToolExecutionContext"):
        CreateTeamTool(service).run(
            {
                "workspace_id": "workspace-001",
                "lead_name": "lead",
                "lead_role": "协调者",
            }
        )


def test_team_tools_validate_direct_arguments_and_require_service_port() -> None:
    with pytest.raises(ToolValidationError, match="content”必须是非空字符串"):
        SendTeamMessageTool(RecordingTeamService()).run(
            {
                "team_id": "team-001",
                "sender_member_id": "lead-001",
                "recipient_member_id": "member-001",
                "content": " ",
            },
            context=_context(),
        )
    with pytest.raises(TypeError, match="完整的 TeamService"):
        CreateTeamTool(object())  # type: ignore[arg-type]
