from __future__ import annotations

from collections.abc import Sequence

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import (
    MessageRole,
    ModelRequest,
    ModelResponse,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.runtime import PendingUserMessageSource, UserInputRuntimeService
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.tools import FakeTool, ToolDefinition, ToolRegistry


class ScriptedModel:
    """记录请求并依次返回模型响应。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self._responses.pop(0)


class SequencePendingUserMessageSource:
    """按调用顺序提供待处理文本，模拟后台完成通知到达。"""

    def __init__(self, batches: tuple[tuple[str, ...], ...]) -> None:
        self._batches = list(batches)
        self.session_ids: list[str] = []

    def drain(self, *, session_id: str) -> Sequence[str]:
        self.session_ids.append(session_id)
        return self._batches.pop(0) if self._batches else ()


class FailingPendingUserMessageSource:
    """模拟通知基础设施暂时不可用。"""

    def drain(self, *, session_id: str) -> Sequence[str]:
        raise RuntimeError("通知仓储不可用。")


def _start(tmp_path, *, session_id: str = "session-001"):
    repository = JsonFileStateRepository(tmp_path / "state")
    session = SessionState.create(
        session_id=session_id,
        tenant_id="local",
        user_id="local",
        project_id="project-001",
    )
    repository.save_session(session)
    start = UserInputRuntimeService(repository).handle(
        UserInputEvent.create(session_id=session.session_id, content="继续处理任务。")
    )
    return repository, session, start


def test_loop_merges_initial_pending_messages_into_the_persisted_user_message(tmp_path) -> None:
    repository, session, start = _start(tmp_path)
    source = SequencePendingUserMessageSource((('<task_notification>完成</task_notification>',),))
    model = ScriptedModel((ModelResponse.text_completion("已收到。"),))
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    loop = MinimalAgentLoop(
        repository,
        model,
        conversation_repository=conversation_repository,
        pending_user_message_source=source,
    )

    loop.execute(start)

    first_message = model.requests[0].conversation[0]
    assert first_message.role is MessageRole.USER
    assert first_message.content == (
        TextBlock("继续处理任务。"),
        TextBlock("<task_notification>完成</task_notification>"),
    )
    assert conversation_repository.get_messages(session.session_id)[0] == first_message
    assert source.session_ids == [session.session_id]


def test_loop_merges_pending_messages_with_tool_results_without_reusing_tool_call_id(
    tmp_path,
) -> None:
    repository, session, start = _start(tmp_path)
    registry = ToolRegistry()
    registry.register(
        FakeTool(
            definition=ToolDefinition(
                name="inspect",
                description="读取检查结果。",
                parameters={"type": "object", "properties": {}},
            ),
            result={"status": "已检查"},
        )
    )
    source = SequencePendingUserMessageSource(
        ((), ("<task_notification>后台完成</task_notification>",))
    )
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(ToolUseBlock("toolu-001", "inspect", {}),),
            ),
            ModelResponse.text_completion("已处理检查和通知。"),
        )
    )
    conversation_repository = JsonFileConversationRepository(tmp_path / "state")
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        pending_user_message_source=source,
    )

    loop.execute(start)

    tool_message = model.requests[1].conversation[2]
    assert tool_message.role is MessageRole.USER
    assert tool_message.content == (
        ToolResultBlock(tool_use_id="toolu-001", content={"status": "已检查"}),
        TextBlock("<task_notification>后台完成</task_notification>"),
    )
    assert sum(
        isinstance(block, ToolResultBlock) and block.tool_use_id == "toolu-001"
        for block in tool_message.content
    ) == 1
    assert source.session_ids == [session.session_id, session.session_id]


def test_loop_ignores_pending_message_source_failure_and_continues_user_task(tmp_path) -> None:
    repository, _, start = _start(tmp_path)
    model = FakeModel(ModelResponse.text_completion("正常完成。"))
    source: PendingUserMessageSource = FailingPendingUserMessageSource()
    loop = MinimalAgentLoop(
        repository,
        model,
        pending_user_message_source=source,
    )

    result = loop.execute(start)

    assert result.response.text == "正常完成。"
    assert model.requests[0].conversation[0].content == (TextBlock("继续处理任务。"),)
    assert callable(source.drain)
