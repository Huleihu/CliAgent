"""基于标准库 logging 的控制台与 JSONL 文件日志配置。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_PACKAGE_LOGGER_NAME = "local_dev_agent"
_CONTEXT_FIELDS = ("event_id", "session_id", "run_id", "step_id")


class _ConsoleFormatter(logging.Formatter):
    """将结构化上下文字段附加到便于终端阅读的日志行。"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化基础日志，并在末尾追加存在的关联标识。"""

        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        context = " ".join(
            f"{field_name}={getattr(record, field_name)}"
            for field_name in _CONTEXT_FIELDS
            if getattr(record, field_name, None) is not None
        )
        exception = self.formatException(record.exc_info) if record.exc_info else ""
        line = f"{timestamp} {record.levelname:<7} {record.name} - {record.getMessage()}"
        if context:
            line = f"{line} {context}"
        return f"{line}\n{exception}" if exception else line


class _JsonLineFormatter(logging.Formatter):
    """将日志记录编码为一行 JSON，便于后续按字段检索。"""

    def format(self, record: logging.LogRecord) -> str:
        """保留日志级别、消息、关联标识与异常摘要。"""

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in _CONTEXT_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    *,
    log_directory: Path,
    level: int = logging.INFO,
) -> logging.Logger:
    """配置包级日志器，并以替换旧 Handler 的方式避免重复输出。"""

    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(_ConsoleFormatter())

    file_handler = RotatingFileHandler(
        log_directory / "agent.jsonl",
        encoding="utf-8",
        maxBytes=1_000_000,
        backupCount=3,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_JsonLineFormatter())

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger
