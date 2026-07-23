import json
import logging

from local_dev_agent.observability.logging import configure_logging


def flush_handlers(logger: logging.Logger) -> None:
    """刷新文件 Handler，确保测试读取到刚写入的日志。"""

    for handler in logger.handlers:
        handler.flush()


def test_configure_logging_writes_contextual_json_lines_and_uses_two_handlers(
    tmp_path,
) -> None:
    logger = configure_logging(log_directory=tmp_path)

    logger.info(
        "已创建运行。",
        extra={"session_id": "session-1", "run_id": "run-1"},
    )
    flush_handlers(logger)

    payload = json.loads((tmp_path / "agent.jsonl").read_text(encoding="utf-8"))
    assert len(logger.handlers) == 2
    assert payload["level"] == "INFO"
    assert payload["message"] == "已创建运行。"
    assert payload["session_id"] == "session-1"
    assert payload["run_id"] == "run-1"


def test_configure_logging_replaces_previous_handlers(tmp_path) -> None:
    logger = configure_logging(log_directory=tmp_path / "first")
    logger = configure_logging(log_directory=tmp_path / "second")

    assert len(logger.handlers) == 2
