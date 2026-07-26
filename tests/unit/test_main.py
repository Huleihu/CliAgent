from datetime import datetime, timezone
from pathlib import Path

from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookDecision, HookEvent, PreToolUseContext
from local_dev_agent.main import create_permission_hook_runner
from local_dev_agent.main import create_subagent_runner
from local_dev_agent.main import create_tool_registry
from local_dev_agent.main import default_workspace
from local_dev_agent.main import execute_prompt
from local_dev_agent.main import build_cli_system_prompt
from local_dev_agent.main import CLI_SYSTEM_PROMPT
from local_dev_agent.main import TODO_PLANNING_SYSTEM_PROMPT
from local_dev_agent.main import TASK_DELEGATION_SYSTEM_PROMPT
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import (
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolUseBlock,
)
from local_dev_agent.skills import SkillCatalog, SkillDocument, SkillMetadata
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_conversation_repository import JsonFileConversationRepository
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.tools import ToolCallRequest
from local_dev_agent.tools.builtin import TaskTool


def test_execute_prompt_connects_input_service_to_agent_loop(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="local",
        user_id="local",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    loop = MinimalAgentLoop(
        repository,
        FakeModel(ModelResponse.text_completion("项目状态正常。")),
    )

    result = execute_prompt(
        prompt="检查项目状态。",
        session=session,
        repository=repository,
        loop=loop,
    )

    assert result.response.text == "项目状态正常。"
    assert result.session.active_run_id is None


def test_create_tool_registry_registers_the_read_only_file_listing_tool(tmp_path) -> None:
    registry = create_tool_registry(tmp_path)

    assert [definition.name for definition in registry.list_definitions()] == [
        "edit_file",
        "list_files",
        "read_file",
        "todo_write",
        "write_file",
    ]


def _skill_catalog() -> SkillCatalog:
    return SkillCatalog(
        documents=(
            SkillDocument(
                metadata=SkillMetadata(
                    name="code-review",
                    description="审查代码中的缺陷。",
                ),
                source_directory="skills/code-review",
                content="---\nname: code-review\n---\n# 完整技能正文\n",
            ),
        )
    )


def test_cli_skill_composition_registers_parent_tool_and_keeps_body_out_of_prompt(
    tmp_path,
) -> None:
    catalog = _skill_catalog()
    registry = create_tool_registry(tmp_path, skill_catalog=catalog)
    prompt = build_cli_system_prompt(catalog)

    assert "load_skill" in [definition.name for definition in registry.list_definitions()]
    assert "code-review" in prompt
    assert "审查代码中的缺陷。" in prompt
    assert "完整技能正文" not in prompt


def test_create_permission_hook_runner_registers_the_s3_policy(tmp_path) -> None:
    request = ToolCallRequest(
        name="bash",
        arguments={"command": "sudo reboot"},
    )

    result = create_permission_hook_runner(tmp_path).trigger(
        HookEvent.PRE_TOOL_USE,
        PreToolUseContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            request=request,
        ),
    )

    assert result.decision is HookDecision.BLOCK
    assert "sudo" in result.message  # type: ignore[operator]


def test_default_workspace_is_the_project_sandbox_directory() -> None:
    expected_workspace = Path(__file__).resolve().parents[2] / "sandbox"

    assert default_workspace() == expected_workspace.resolve()


def test_cli_todo_planning_prompt_mentions_the_tool_and_status_updates() -> None:
    assert "todo_write" in TODO_PLANNING_SYSTEM_PROMPT
    assert "in_progress" in TODO_PLANNING_SYSTEM_PROMPT
    assert "completed" in TODO_PLANNING_SYSTEM_PROMPT


def test_cli_system_prompt_adds_bounded_task_delegation_guidance() -> None:
    assert TODO_PLANNING_SYSTEM_PROMPT in CLI_SYSTEM_PROMPT
    assert TASK_DELEGATION_SYSTEM_PROMPT in CLI_SYSTEM_PROMPT
    assert "task" in TASK_DELEGATION_SYSTEM_PROMPT
    assert "简单任务不要委派" in TASK_DELEGATION_SYSTEM_PROMPT


class ScriptedModel:
    """按顺序返回父子 Agent 响应，验证 CLI 装配闭环。"""

    def __init__(self, responses: tuple[ModelResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一项预设响应。"""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("测试模型没有更多预设响应。")
        return self._responses.pop(0)


def test_cli_composition_registers_task_and_keeps_it_out_of_child_tools(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = JsonFileStateRepository(workspace / "var" / "state")
    conversation_repository = JsonFileConversationRepository(workspace / "var" / "state")
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
        created_at=timestamp,
    )
    repository.save_session(session)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-parent",
                        name="task",
                        input={"description": "调查测试框架。"},
                    ),
                ),
            ),
            ModelResponse.text_completion("子 Agent 返回 pytest。"),
            ModelResponse.text_completion("父 Agent 已验收子任务结论。"),
        )
    )
    catalog = _skill_catalog()
    registry = create_tool_registry(workspace, skill_catalog=catalog)
    hook_runner = create_permission_hook_runner(workspace)
    registry.register(
        TaskTool(
            create_subagent_runner(
                repository=repository,
                conversation_repository=conversation_repository,
                model=model,
                parent_registry=registry,
                hook_runner=hook_runner,
            )
        )
    )
    loop = MinimalAgentLoop(
        repository,
        model,
        registry,
        conversation_repository,
        hook_runner=hook_runner,
        system_prompt=build_cli_system_prompt(catalog),
    )

    result = execute_prompt(
        prompt="请调查项目测试框架。",
        session=session,
        repository=repository,
        loop=loop,
    )

    parent_request, child_request, parent_follow_up = model.requests
    assert result.response.text == "父 Agent 已验收子任务结论。"
    assert "task" in [definition.name for definition in parent_request.tools]
    assert "load_skill" in [definition.name for definition in parent_request.tools]
    assert "task" not in [definition.name for definition in child_request.tools]
    assert "todo_write" not in [definition.name for definition in child_request.tools]
    assert "load_skill" not in [definition.name for definition in child_request.tools]
    assert child_request.system_prompt != build_cli_system_prompt(catalog)
    assert parent_follow_up.conversation[2].content[0].content["summary"] == (
        "子 Agent 返回 pytest。"
    )


def test_cli_skill_tool_result_is_returned_to_the_next_parent_model_request(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = JsonFileStateRepository(workspace / "var" / "state")
    conversation_repository = JsonFileConversationRepository(workspace / "var" / "state")
    session = SessionState.create(
        session_id="session-parent",
        tenant_id="local",
        user_id="local",
        project_id=str(workspace),
    )
    repository.save_session(session)
    model = ScriptedModel(
        (
            ModelResponse(
                stop_reason=StopReason.TOOL_USE,
                content=(
                    ToolUseBlock(
                        tool_use_id="toolu-skill",
                        name="load_skill",
                        input={"name": "code-review"},
                    ),
                ),
            ),
            ModelResponse.text_completion("已根据代码审查技能完成检查。"),
        )
    )
    catalog = _skill_catalog()
    loop = MinimalAgentLoop(
        repository,
        model,
        create_tool_registry(workspace, skill_catalog=catalog),
        conversation_repository,
        hook_runner=create_permission_hook_runner(workspace),
        system_prompt=build_cli_system_prompt(catalog),
    )

    result = execute_prompt(
        prompt="请审查当前代码。",
        session=session,
        repository=repository,
        loop=loop,
    )

    first_request, follow_up_request = model.requests
    assert result.response.text == "已根据代码审查技能完成检查。"
    assert "完整技能正文" not in first_request.system_prompt
    assert follow_up_request.conversation[2].content[0].content["content"] == (
        "---\nname: code-review\n---\n# 完整技能正文\n"
    )
