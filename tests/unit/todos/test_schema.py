from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from local_dev_agent.todos import TodoItem, TodoSnapshot, TodoStatus


def test_snapshot_preserves_items_and_reports_status_counts() -> None:
    updated_at = datetime(2026, 7, 25, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    todos = [
        TodoItem(content="检查现有工具框架", status=TodoStatus.COMPLETED),
        TodoItem(
            content="实现待办领域契约",
            status=TodoStatus.IN_PROGRESS,
            active_form="正在实现待办领域契约",
        ),
        TodoItem(content="补充单元测试", status=TodoStatus.PENDING),
    ]

    snapshot = TodoSnapshot.create(
        todo_list_id="default",
        todos=todos,
        updated_at=updated_at,
    )
    todos.clear()

    assert snapshot.todos[1].active_form == "正在实现待办领域契约"
    assert len(snapshot.todos) == 3
    assert snapshot.pending_count == 1
    assert snapshot.in_progress_count == 1
    assert snapshot.completed_count == 1
    assert snapshot.updated_at == datetime(2026, 7, 25, 2, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("content", "active_form", "message"),
    [
        ("", None, "字段“content”必须是非空字符串"),
        ("   ", None, "字段“content”必须是非空字符串"),
        ("检查文件", "", "字段“active_form”必须是非空字符串"),
    ],
)
def test_todo_item_rejects_blank_display_text(
    content: str,
    active_form: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TodoItem(
            content=content,
            status=TodoStatus.PENDING,
            active_form=active_form,
        )


def test_todo_item_rejects_an_unknown_status() -> None:
    with pytest.raises(ValueError, match="待办事项状态必须是 TodoStatus 枚举值"):
        TodoItem(content="检查文件", status="pending")  # type: ignore[arg-type]


def test_snapshot_rejects_non_tuple_or_invalid_items() -> None:
    updated_at = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="待办清单必须是 TodoItem 元组"):
        TodoSnapshot(
            todo_list_id="default",
            todos=[TodoItem(content="检查文件", status=TodoStatus.PENDING)],  # type: ignore[arg-type]
            updated_at=updated_at,
        )
    with pytest.raises(ValueError, match="待办清单必须是 TodoItem 元组"):
        TodoSnapshot(
            todo_list_id="default",
            todos=("检查文件",),  # type: ignore[arg-type]
            updated_at=updated_at,
        )


def test_snapshot_rejects_blank_list_id_and_naive_timestamp() -> None:
    todo = TodoItem(content="检查文件", status=TodoStatus.PENDING)

    with pytest.raises(ValueError, match="字段“todo_list_id”必须是非空字符串"):
        TodoSnapshot.create(todo_list_id="  ", todos=(todo,))
    with pytest.raises(ValueError, match="待办清单时间戳必须包含时区信息"):
        TodoSnapshot.create(
            todo_list_id="default",
            todos=(todo,),
            updated_at=datetime(2026, 7, 25, 10, 0),
        )


def test_todo_models_cannot_be_mutated_directly() -> None:
    todo = TodoItem(content="检查文件", status=TodoStatus.PENDING)
    snapshot = TodoSnapshot.create(todo_list_id="default", todos=(todo,))

    with pytest.raises(FrozenInstanceError):
        todo.status = TodoStatus.COMPLETED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.todos = ()  # type: ignore[misc]
