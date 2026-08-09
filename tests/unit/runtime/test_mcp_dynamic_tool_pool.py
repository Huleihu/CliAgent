from __future__ import annotations

from datetime import datetime, timezone

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.mcp.adapters.fake import (
    FakeMcpClient,
    FakeMcpClientConnector,
    InMemoryMcpServerCatalog,
)
from local_dev_agent.mcp.adapters.tool_registry import ToolRegistryMcpToolPool
from local_dev_agent.mcp.ports import McpCallResult
from local_dev_agent.mcp.schema import McpServerConfiguration, McpToolDefinition
from local_dev_agent.mcp.service import McpConnectionService
from local_dev_agent.models.ports import ModelRequest, ModelResponse, StopReason, ToolUseBlock
from local_dev_agent.runtime import MinimalAgentLoop, UserInputRuntimeService
from local_dev_agent.skills import SkillCatalog
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.system_prompt import create_cli_system_prompt_provider
from local_dev_agent.tools import ToolRegistry
from local_dev_agent.tools.builtin import ConnectMcpTool


class _ScriptedModel:
    """按顺序提供模型响应，并保留每轮实际收到的工具快照。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def test_connect_mcp_refreshes_tools_and_system_prompt_on_the_next_model_turn(tmp_path) -> None:
    timestamp = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)
    state_repository = JsonFileStateRepository(tmp_path / "state")
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    state_repository.save_session(session)
    start = UserInputRuntimeService(state_repository).handle(
        UserInputEvent.create(
            session_id=session.session_id,
            content="连接文档服务并搜索 S19。",
            occurred_at=timestamp,
        )
    )
    search = McpToolDefinition(
        "search",
        "搜索项目文档",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )
    client = FakeMcpClient(
        [search],
        {"search": lambda _arguments, _context: McpCallResult(content=({"type": "text", "text": "S19 文档"},))},
    )
    registry = ToolRegistry()
    tool_pool = ToolRegistryMcpToolPool(registry)
    registry.register(
        ConnectMcpTool(
            McpConnectionService(
                server_catalog=InMemoryMcpServerCatalog([McpServerConfiguration("docs")]),
                connector=FakeMcpClientConnector({"docs": client}),
                tool_pool=tool_pool,
            )
        )
    )
    model = _ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(tool_use_id="connect-1", name="connect_mcp", input={"name": "docs"}),
                ),
            ),
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="search-1",
                        name="mcp__docs__search",
                        input={"query": "S19"},
                    ),
                ),
            ),
            ModelResponse.text_completion("已找到 S19 文档。"),
        )
    )
    provider = create_cli_system_prompt_provider(
        workspace=tmp_path,
        registry=registry,
        skill_catalog=SkillCatalog(),
    )

    result = MinimalAgentLoop(
        state_repository,
        model,
        registry,
        conversation_repository,
        system_prompt_provider=provider,
    ).execute(start, occurred_at=timestamp)

    assert result.response.text == "已找到 S19 文档。"
    assert [definition.name for definition in model.requests[0].tools] == ["connect_mcp"]
    assert [definition.name for definition in model.requests[1].tools] == [
        "connect_mcp",
        "mcp__docs__search",
    ]
    assert "当前已连接并可调用的 MCP 工具：mcp__docs__search。" in model.requests[1].system_prompt  # type: ignore[operator]
    assert client.calls[0].context.run_id
