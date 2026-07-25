from datetime import datetime, timezone
from pathlib import Path

from local_dev_agent.domain.state import SessionState
from local_dev_agent.hooks import HookDecision, HookEvent, PreToolUseContext
from local_dev_agent.main import create_permission_hook_runner
from local_dev_agent.main import create_tool_registry
from local_dev_agent.main import default_workspace
from local_dev_agent.main import execute_prompt
from local_dev_agent.main import TODO_PLANNING_SYSTEM_PROMPT
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import ModelResponse
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository
from local_dev_agent.tools import ToolCallRequest


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
