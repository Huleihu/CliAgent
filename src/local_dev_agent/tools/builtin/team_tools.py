"""仅供父 Agent 调用的 Team 管理、派活和成员通信工具。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from local_dev_agent.teams import Team, TeamAssignment, TeamMember, TeamMessage, TeamService

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


_REQUIRED_SERVICE_METHODS = (
    "create_team",
    "add_teammate",
    "assign_work",
    "send_message",
)


def _service(value: object) -> TeamService:
    """拒绝工具直接依赖仓储，确保 Team 规则仍由应用服务统一执行。"""

    if not all(callable(getattr(value, method_name, None)) for method_name in _REQUIRED_SERVICE_METHODS):
        raise TypeError("Team 工具必须提供完整的 TeamService 应用服务。")
    return value  # type: ignore[return-value]


def _context(value: ToolExecutionContext | None) -> ToolExecutionContext:
    """Team 的成员身份必须可追溯到当前受控工具执行上下文。"""

    if value is None:
        raise ToolExecutionError("Team 工具必须在 ToolExecutionContext 中执行。")
    return value


def _text(arguments: Mapping[str, object], field_name: str) -> str:
    """读取模型工具协议中的必填非空文本字段。"""

    value = arguments.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")
    return value


def _optional_text(arguments: Mapping[str, object], field_name: str) -> str | None:
    """读取允许省略的文本字段；显式空白仍视为无效输入。"""

    if field_name not in arguments:
        return None
    return _text(arguments, field_name)


def _team_data(team: Team) -> dict[str, object]:
    return {
        "team_id": team.team_id,
        "workspace_id": team.workspace_id,
        "lead_member_id": team.lead_member_id,
        "status": team.status.value,
    }


def _member_data(member: TeamMember) -> dict[str, object]:
    return {
        "member_id": member.member_id,
        "team_id": member.team_id,
        "name": member.name,
        "role": member.role,
        "session_id": member.session_id,
        "status": member.status.value,
    }


def _assignment_data(assignment: TeamAssignment) -> dict[str, object]:
    return {
        "assignment_id": assignment.assignment_id,
        "team_id": assignment.team_id,
        "assigned_by_member_id": assignment.assigned_by_member_id,
        "assignee_member_id": assignment.assignee_member_id,
        "prompt": assignment.prompt,
        "status": assignment.status.value,
        "project_task_id": assignment.project_task_id,
    }


def _message_data(message: TeamMessage) -> dict[str, object]:
    return {
        "message_id": message.message_id,
        "team_id": message.team_id,
        "sender_member_id": message.sender_member_id,
        "recipient_member_id": message.recipient_member_id,
        "sequence": message.sequence,
        "message_type": message.message_type.value,
        "delivery_status": message.delivery_status.value,
    }


def _operation_id(context: ToolExecutionContext, *, prefix: str) -> str:
    """把一次可审计的工具调用转换为重放时稳定的领域标识。"""

    return f"{prefix}-{context.call_id or context.step_id}"


class CreateTeamTool(Tool):
    """以当前父 Agent Session 创建 Team 和其 Lead 成员。"""

    def __init__(self, service: TeamService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(
            name="create_team",
            description="创建一个持久 Team，并将当前会话绑定为其 Lead。",
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "lead_name": {"type": "string"},
                    "lead_role": {"type": "string"},
                },
                "required": ["workspace_id", "lead_name", "lead_role"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        team, lead = self._service.create_team(
            workspace_id=_text(arguments, "workspace_id"),
            lead_name=_text(arguments, "lead_name"),
            lead_role=_text(arguments, "lead_role"),
            lead_session_id=execution_context.session_id,
        )
        return {"team": _team_data(team), "lead": _member_data(lead)}


class AddTeammateTool(Tool):
    """由当前 Team Lead 为已知 Session 注册持久 Team 成员身份。"""

    def __init__(
        self,
        service: TeamService,
        *,
        on_teammate_added: Callable[[TeamMember], None] | None = None,
    ) -> None:
        self._service = _service(service)
        if on_teammate_added is not None and not callable(on_teammate_added):
            raise TypeError("on_teammate_added 必须是可调用对象或 None。")
        self._on_teammate_added = on_teammate_added
        self._definition = ToolDefinition(
            name="add_teammate",
            description="将一个已知会话注册为当前 Team 的持久成员，不启动 Agent。",
            parameters={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "lead_member_id": {"type": "string"},
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "session_id": {"type": "string"},
                },
                "required": ["team_id", "lead_member_id", "name", "role", "session_id"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        member = self._service.add_teammate(
            team_id=_text(arguments, "team_id"),
            lead_member_id=_text(arguments, "lead_member_id"),
            lead_session_id=execution_context.session_id,
            name=_text(arguments, "name"),
            role=_text(arguments, "role"),
            session_id=_text(arguments, "session_id"),
        )
        if self._on_teammate_added is not None:
            self._on_teammate_added(member)
        return _member_data(member)


class AssignTeamWorkTool(Tool):
    """由当前 Team Lead 创建可恢复的工作分配，并投递 assignment 提示。"""

    def __init__(self, service: TeamService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(
            name="assign_team_work",
            description="向 Team 成员派发可恢复工作，并保留可选的 S12 项目任务引用。",
            parameters={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "lead_member_id": {"type": "string"},
                    "assignee_member_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "project_task_id": {"type": "string"},
                },
                "required": ["team_id", "lead_member_id", "assignee_member_id", "prompt"],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        assignment = self._service.assign_work(
            team_id=_text(arguments, "team_id"),
            assigned_by_member_id=_text(arguments, "lead_member_id"),
            assigned_by_session_id=execution_context.session_id,
            assignee_member_id=_text(arguments, "assignee_member_id"),
            prompt=_text(arguments, "prompt"),
            project_task_id=_optional_text(arguments, "project_task_id"),
            assignment_id=_operation_id(execution_context, prefix="assignment"),
        )
        return _assignment_data(assignment)


class SendTeamMessageTool(Tool):
    """由当前成员投递带稳定身份的普通 Team 消息。"""

    def __init__(self, service: TeamService) -> None:
        self._service = _service(service)
        self._definition = ToolDefinition(
            name="send_team_message",
            description="向 Team 成员投递一条普通消息，不创建工作分配。",
            parameters={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "sender_member_id": {"type": "string"},
                    "recipient_member_id": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": [
                    "team_id",
                    "sender_member_id",
                    "recipient_member_id",
                    "content",
                ],
            },
            tags=("state",),
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        execution_context = _context(context)
        message = self._service.send_message(
            team_id=_text(arguments, "team_id"),
            sender_member_id=_text(arguments, "sender_member_id"),
            sender_session_id=execution_context.session_id,
            recipient_member_id=_text(arguments, "recipient_member_id"),
            content=_text(arguments, "content"),
            idempotency_key=_operation_id(execution_context, prefix="team-message"),
            message_id=_operation_id(execution_context, prefix="message"),
        )
        return _message_data(message)
