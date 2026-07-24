from datetime import datetime, timezone
from pathlib import Path

from local_dev_agent.domain.state import SessionState
from local_dev_agent.main import create_tool_registry
from local_dev_agent.main import default_workspace
from local_dev_agent.main import execute_prompt
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import ModelResponse
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository


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
        "list_files",
        "read_file",
    ]


def test_default_workspace_is_the_project_sandbox_directory() -> None:
    expected_workspace = Path(__file__).resolve().parents[2] / "sandbox"

    assert default_workspace() == expected_workspace.resolve()
