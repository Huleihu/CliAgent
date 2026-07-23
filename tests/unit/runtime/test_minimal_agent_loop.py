from datetime import datetime, timezone

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import (
    RunStatus,
    SessionState,
    SessionStatus,
    StepStatus,
)
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.runtime.input_service import UserInputRuntimeService
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository


def test_minimal_agent_loop_completes_a_text_response_and_persists_states(
    tmp_path,
) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )
    repository.save_session(session)
    event = UserInputEvent.create(
        event_id="event-1",
        session_id=session.session_id,
        content="检查项目状态。",
        occurred_at=timestamp,
    )
    start = UserInputRuntimeService(repository).handle(event)
    model = FakeModel("项目状态正常。")

    result = MinimalAgentLoop(repository, model).execute(
        start,
        occurred_at=timestamp,
    )

    assert result.response.text == "项目状态正常。"
    assert model.requests[0].user_input == event.content
    assert result.step.status is StepStatus.SUCCEEDED
    assert result.run.status is RunStatus.COMPLETED
    assert result.session.status is SessionStatus.ACTIVE
    assert result.session.active_run_id is None
    assert repository.get_session(session.session_id) == result.session
    assert repository.get_run(result.run.run_id) == result.run
    assert repository.get_step(result.step.step_id) == result.step
    assert [item.target_status for item in result.run.transition_history] == [
        RunStatus.RECOVERING,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]
