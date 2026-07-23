import json
from datetime import datetime, timezone

import pytest

from local_dev_agent.domain.state import (
    RunState,
    RunStatus,
    SessionState,
    StepState,
    StepStatus,
    StepType,
)
from local_dev_agent.storage.errors import (
    CorruptedStateFileError,
    StateVersionConflictError,
)
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository


def create_session(timestamp: datetime) -> SessionState:
    """创建测试所需的会话。"""

    return SessionState.create(
        session_id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        project_id="project-1",
        created_at=timestamp,
    )


def test_repository_persists_state_across_instances(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = create_session(timestamp)
    run = RunState.create(
        session_id=session.session_id,
        run_id="run-1",
        created_at=timestamp,
    )
    step = StepState.create(
        run_id=run.run_id,
        step_id="step-1",
        step_type=StepType.TOOL,
        created_at=timestamp,
    )

    repository.save_session(session)
    repository.save_run(run)
    repository.save_step(step)

    reloaded_repository = JsonFileStateRepository(tmp_path)

    assert reloaded_repository.get_session(session.session_id) == session
    assert reloaded_repository.get_run(run.run_id) == run
    assert reloaded_repository.get_step(step.step_id) == step


def test_repository_lists_states_by_their_parent_identifier(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    run = RunState.create(session_id="session-1", run_id="run-1", created_at=timestamp)
    other_run = RunState.create(
        session_id="session-2",
        run_id="run-2",
        created_at=timestamp,
    )
    step = StepState.create(
        run_id=run.run_id,
        step_id="step-1",
        step_type=StepType.MODEL,
        created_at=timestamp,
    )
    other_step = StepState.create(
        run_id=other_run.run_id,
        step_id="step-2",
        step_type=StepType.VERIFY,
        created_at=timestamp,
    )

    repository.save_run(run)
    repository.save_run(other_run)
    repository.save_step(step)
    repository.save_step(other_step)

    assert repository.list_runs("session-1") == (run,)
    assert repository.list_steps("run-1") == (step,)


def test_repository_requires_the_next_state_version(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    run = RunState.create(session_id="session-1", run_id="run-1", created_at=timestamp)
    repository.save_run(run)

    updated = run.transition_to(RunStatus.RECOVERING, occurred_at=timestamp)
    repository.save_run(updated)

    with pytest.raises(StateVersionConflictError, match="状态版本冲突"):
        repository.save_run(run)


def test_repository_writes_a_readable_versioned_json_file(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    session = create_session(timestamp)
    repository.save_session(session)
    session = session.start_run("run-1", occurred_at=timestamp)

    repository.save_session(session)

    state_file = tmp_path / "sessions" / "session-1.json"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["entity_type"] == "session"
    assert payload["state"]["active_run_id"] == "run-1"
    assert payload["state"]["transition_history"][0]["reason"] == "启动首个运行。"


def test_repository_returns_none_for_a_missing_state(tmp_path) -> None:
    repository = JsonFileStateRepository(tmp_path)

    assert repository.get_session("missing-session") is None
    assert repository.get_run("missing-run") is None
    assert repository.get_step("missing-step") is None


def test_repository_reports_a_corrupted_json_file_in_chinese(tmp_path) -> None:
    state_file = tmp_path / "runs" / "run-1.json"
    state_file.parent.mkdir()
    state_file.write_text("{不是有效 JSON", encoding="utf-8")
    repository = JsonFileStateRepository(tmp_path)

    with pytest.raises(CorruptedStateFileError, match="状态文件.*已损坏"):
        repository.get_run("run-1")


def test_repository_restores_transition_history(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    repository = JsonFileStateRepository(tmp_path)
    step = StepState.create(
        run_id="run-1",
        step_id="step-1",
        step_type=StepType.TOOL,
        created_at=timestamp,
    )
    repository.save_step(step)
    step = step.transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
    repository.save_step(step)
    step = step.transition_to(StepStatus.SUCCEEDED, occurred_at=timestamp)

    repository.save_step(step)

    restored = repository.get_step("step-1")
    assert restored is not None
    assert restored.transition_history == step.transition_history
