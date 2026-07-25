import json
from datetime import datetime, timezone

import pytest

from local_dev_agent.todos import (
    CorruptedTodoFileError,
    JsonFileTodoRepository,
    TodoItem,
    TodoSnapshot,
    TodoStatus,
)


def create_snapshot(
    *,
    updated_at: datetime,
    todos: tuple[TodoItem, ...],
) -> TodoSnapshot:
    """创建测试所需的固定时间待办快照。"""

    return TodoSnapshot.create(
        todo_list_id="default",
        todos=todos,
        updated_at=updated_at,
    )


def test_repository_returns_an_empty_snapshot_for_a_missing_list(tmp_path) -> None:
    repository = JsonFileTodoRepository(tmp_path)

    snapshot = repository.load("default")

    assert snapshot.todo_list_id == "default"
    assert snapshot.todos == ()
    assert not (tmp_path / "default.json").exists()


def test_repository_persists_a_snapshot_across_instances(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    snapshot = create_snapshot(
        updated_at=timestamp,
        todos=(
            TodoItem(content="检查现有代码", status=TodoStatus.COMPLETED),
            TodoItem(
                content="实现 JSON 仓储",
                status=TodoStatus.IN_PROGRESS,
                active_form="正在实现 JSON 仓储",
            ),
        ),
    )

    JsonFileTodoRepository(tmp_path).replace(snapshot)

    assert JsonFileTodoRepository(tmp_path).load("default") == snapshot


def test_repository_replaces_the_complete_previous_snapshot(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    repository = JsonFileTodoRepository(tmp_path)
    repository.replace(
        create_snapshot(
            updated_at=timestamp,
            todos=(TodoItem(content="旧事项", status=TodoStatus.PENDING),),
        )
    )
    replacement = create_snapshot(
        updated_at=datetime(2026, 7, 25, 10, 1, tzinfo=timezone.utc),
        todos=(TodoItem(content="新事项", status=TodoStatus.COMPLETED),),
    )

    returned = repository.replace(replacement)

    assert returned == replacement
    assert repository.load("default") == replacement


def test_repository_writes_a_readable_versioned_json_file(tmp_path) -> None:
    timestamp = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    snapshot = create_snapshot(
        updated_at=timestamp,
        todos=(
            TodoItem(
                content="实现 JSON 仓储",
                status=TodoStatus.IN_PROGRESS,
                active_form="正在实现 JSON 仓储",
            ),
        ),
    )
    repository = JsonFileTodoRepository(tmp_path)

    repository.replace(snapshot)

    payload = json.loads((tmp_path / "default.json").read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "entity_type": "todo_list",
        "state": {
            "todo_list_id": "default",
            "updated_at": "2026-07-25T10:00:00+00:00",
            "todos": [
                {
                    "content": "实现 JSON 仓储",
                    "status": "in_progress",
                    "active_form": "正在实现 JSON 仓储",
                }
            ],
        },
    }


@pytest.mark.parametrize("content", ["{不是有效 JSON", "[]"])
def test_repository_reports_corrupted_files_in_chinese(tmp_path, content: str) -> None:
    path = tmp_path / "default.json"
    path.write_text(content, encoding="utf-8")
    repository = JsonFileTodoRepository(tmp_path)

    with pytest.raises(CorruptedTodoFileError, match="待办清单文件.*已损坏"):
        repository.load("default")


def test_repository_rejects_an_unsupported_schema_or_mismatched_list_id(tmp_path) -> None:
    repository = JsonFileTodoRepository(tmp_path)
    path = tmp_path / "default.json"
    path.write_text(
        json.dumps({"schema_version": 2, "entity_type": "todo_list", "state": {}}),
        encoding="utf-8",
    )

    with pytest.raises(CorruptedTodoFileError, match="待办清单文件.*已损坏"):
        repository.load("default")

    snapshot = create_snapshot(
        updated_at=datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        todos=(),
    )
    mismatched = {
        "schema_version": 1,
        "entity_type": "todo_list",
        "state": {
            "todo_list_id": "other",
            "updated_at": snapshot.updated_at.isoformat(),
            "todos": [],
        },
    }
    path.write_text(json.dumps(mismatched), encoding="utf-8")

    with pytest.raises(CorruptedTodoFileError, match="待办清单文件.*已损坏"):
        repository.load("default")


@pytest.mark.parametrize("todo_list_id", ["", " ", ".", "..", "../other", "nested/list"])
def test_repository_rejects_path_like_list_identifiers(tmp_path, todo_list_id: str) -> None:
    repository = JsonFileTodoRepository(tmp_path)

    with pytest.raises(ValueError, match="待办清单标识不能包含路径分隔符"):
        repository.load(todo_list_id)
