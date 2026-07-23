from datetime import datetime, timezone

import pytest

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import (
    RunState,
    SessionState,
    SessionStatus,
    StepStatus,
    StepType,
)
from local_dev_agent.runtime.errors import SessionNotFoundError
from local_dev_agent.runtime.input_service import UserInputRuntimeService
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository


def create_session(timestamp: datetime) -> SessionState:
    """创建测试所需、尚未处理输入的会话。"""

    return SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )


def test_service_creates_and_persists_the_minimum_runtime_states(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    original_session = create_session(timestamp)
    repository.save_session(original_session)
    event = UserInputEvent.create(
        event_id="event-1",
        session_id=original_session.session_id,
        content="检查项目状态。",
        occurred_at=timestamp,
    )

    result = UserInputRuntimeService(repository).handle(event)

    assert result.event is event
    assert result.session.status is SessionStatus.ACTIVE
    assert result.session.active_run_id == result.run.run_id
    assert result.run.session_id == original_session.session_id
    assert result.first_step.run_id == result.run.run_id
    assert result.first_step.step_type is StepType.PLAN
    assert result.first_step.status is StepStatus.PENDING
    assert repository.get_session(original_session.session_id) == result.session
    assert repository.get_run(result.run.run_id) == result.run
    assert repository.get_step(result.first_step.step_id) == result.first_step


def test_service_rejects_an_event_for_a_missing_session(tmp_path) -> None:
    repository = JsonFileStateRepository(tmp_path)
    event = UserInputEvent.create(
        session_id="missing-session",
        content="开始任务。",
    )

    with pytest.raises(SessionNotFoundError, match="找不到用户输入事件关联的会话"):
        UserInputRuntimeService(repository).handle(event)


def test_service_rejects_a_new_input_while_a_run_is_active(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = create_session(timestamp)
    repository.save_session(session)
    active_run = RunState.create(
        session_id=session.session_id,
        run_id="run-1",
        created_at=timestamp,
    )
    repository.save_run(active_run)
    active_session = session.start_run(active_run.run_id, occurred_at=timestamp)
    repository.save_session(active_session)
    event = UserInputEvent.create(
        session_id=session.session_id,
        content="另一条输入。",
        occurred_at=timestamp,
    )

    with pytest.raises(ValueError, match="已有活跃运行"):
        UserInputRuntimeService(repository).handle(event)

    assert repository.list_runs(session.session_id) == (active_run,)
