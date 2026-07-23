import json
import logging
from datetime import datetime, timezone

from local_dev_agent.domain.messages import UserInputEvent
from local_dev_agent.domain.state import SessionState
from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import ModelResponse
from local_dev_agent.observability.logging import configure_logging
from local_dev_agent.runtime.input_service import UserInputRuntimeService
from local_dev_agent.runtime.loop import MinimalAgentLoop
from local_dev_agent.storage.json_state_repository import JsonFileStateRepository


def flush_handlers(logger: logging.Logger) -> None:
    """刷新文件 Handler，确保测试读取到完整日志。"""

    for handler in logger.handlers:
        handler.flush()


def test_runtime_and_agent_loop_record_key_lifecycle_events(tmp_path) -> None:
    timestamp = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    logger = configure_logging(log_directory=tmp_path / "logs")
    repository = JsonFileStateRepository(tmp_path / "state")
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
    MinimalAgentLoop(
        repository,
        FakeModel(ModelResponse.text_completion("项目状态正常。")),
    ).execute(
        start,
        occurred_at=timestamp,
    )
    flush_handlers(logger)

    entries = [
        json.loads(line)
        for line in (tmp_path / "logs" / "agent.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [entry["message"] for entry in entries] == [
        "已接收用户输入。",
        "已创建并保存运行与规划步骤。",
        "运行开始恢复。",
        "开始模型调用。",
        "模型调用完成。",
        "运行已完成。",
    ]
    assert all(entry["session_id"] == session.session_id for entry in entries)
    assert entries[-1]["run_id"] == start.run.run_id
