"""以 append-only JSONL 保存工作树生命周期事件。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import RLock

from ..errors import WorktreeEventJournalError
from ..schema import Worktree, WorktreeEventType, WorktreeLifecycleEvent


class JsonlWorktreeEventJournal:
    """在单进程内串行追加 JSONL 事件；跨进程锁不属于当前范围。"""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("工作树事件日志路径必须是 Path 对象。")
        self._path = path
        self._lock = RLock()

    def find_by_operation_id(self, operation_id: str) -> WorktreeLifecycleEvent | None:
        """顺序读取追加日志，返回首个匹配的稳定幂等事件。"""

        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("工作树操作标识必须是非空字符串。")
        with self._lock:
            for event in self._read_events():
                if event.operation_id == operation_id:
                    return event
        return None

    def append(self, event: WorktreeLifecycleEvent) -> None:
        """仅追加新操作标识，并在写入后 fsync 以降低断电丢失风险。"""

        if not isinstance(event, WorktreeLifecycleEvent):
            raise TypeError("工作树事件必须是 WorktreeLifecycleEvent 对象。")
        with self._lock:
            if self.find_by_operation_id(event.operation_id) is not None:
                raise WorktreeEventJournalError(detail="工作树操作标识已存在，不能重复追加")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self._path.open("a", encoding="utf-8", newline="\n") as file:
                    file.write(json.dumps(_encode_event(event), ensure_ascii=False) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
            except OSError as error:
                raise WorktreeEventJournalError(detail=str(error)) from error

    def _read_events(self) -> tuple[WorktreeLifecycleEvent, ...]:
        """解析已追加的每一行；任一损坏行都拒绝继续推断重放事实。"""

        if not self._path.exists():
            return ()
        try:
            with self._path.open(encoding="utf-8") as file:
                return tuple(
                    _decode_event(line, line_number=line_number)
                    for line_number, line in enumerate(file, start=1)
                    if line.strip()
                )
        except OSError as error:
            raise WorktreeEventJournalError(detail=str(error)) from error


def _encode_event(event: WorktreeLifecycleEvent) -> dict[str, object]:
    """将领域事件编码为固定信封，避免未来日志字段无版本演进。"""

    return {
        "schema_version": 1,
        "entity_type": "worktree_lifecycle_event",
        "state": {
            "event_type": event.event_type.value,
            "operation_id": event.operation_id,
            "worktree": {
                "name": event.worktree.name,
                "directory": event.worktree.directory,
                "branch": event.worktree.branch,
                "base_commit": event.worktree.base_commit,
            },
            "task_id": event.task_id,
            "occurred_at": event.occurred_at.isoformat(),
        },
    }


def _decode_event(line: str, *, line_number: int) -> WorktreeLifecycleEvent:
    """把单行 JSONL 恢复为领域事件，并把任何格式问题标注为行号。"""

    try:
        payload = json.loads(line)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or payload.get("entity_type") != "worktree_lifecycle_event"
            or not isinstance(payload.get("state"), dict)
        ):
            raise ValueError("事件信封不受支持")
        state = payload["state"]
        worktree_state = state.get("worktree")
        if not isinstance(worktree_state, dict):
            raise ValueError("工作树事件缺少工作树对象")
        task_id = state.get("task_id")
        return WorktreeLifecycleEvent(
            event_type=WorktreeEventType(_require_text(state, "event_type")),
            operation_id=_require_text(state, "operation_id"),
            worktree=Worktree(
                name=_require_text(worktree_state, "name"),
                directory=_require_text(worktree_state, "directory"),
                branch=_require_text(worktree_state, "branch"),
                base_commit=_require_text(worktree_state, "base_commit"),
            ),
            task_id=task_id,
            occurred_at=datetime.fromisoformat(_require_text(state, "occurred_at")),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise WorktreeEventJournalError(
            detail=f"第 {line_number} 行格式损坏或不受支持",
        ) from error


def _require_text(payload: dict[str, object], field_name: str) -> str:
    """读取 JSON 状态对象中的必填非空字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串")
    return value
