import pytest

from local_dev_agent.todos import JsonFileTodoRepository, TodoItem, TodoSnapshot, TodoStatus
from local_dev_agent.tools.builtin import TodoWriteTool
from local_dev_agent.tools.errors import ToolValidationError


def test_todo_write_replaces_the_persisted_list_and_returns_counts(tmp_path) -> None:
    repository = JsonFileTodoRepository(tmp_path / "todos")
    tool = TodoWriteTool(repository)

    result = tool.run(
        {
            "todos": [
                {"content": "检查现有代码", "status": "completed"},
                {
                    "content": "实现工具",
                    "status": "in_progress",
                    "active_form": "正在实现工具",
                },
                {"content": "补充测试", "status": "pending"},
            ],
        }
    )

    assert result == {
        "todo_list_id": "default",
        "total": 3,
        "pending": 1,
        "in_progress": 1,
        "completed": 1,
    }
    assert repository.load("default").todos == (
        TodoItem(content="检查现有代码", status=TodoStatus.COMPLETED),
        TodoItem(
            content="实现工具",
            status=TodoStatus.IN_PROGRESS,
            active_form="正在实现工具",
        ),
        TodoItem(content="补充测试", status=TodoStatus.PENDING),
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "字段“todos”必须是数组"),
        ({"todos": [{}]}, "todos\\[0\\].content"),
        (
            {"todos": [{"content": "实现工具", "status": "running"}]},
            "pending、in_progress 或 completed",
        ),
        (
            {
                "todos": [
                    {
                        "content": "实现工具",
                        "status": "pending",
                        "active_form": " ",
                    }
                ]
            },
            "todos\\[0\\].active_form",
        ),
    ],
)
def test_todo_write_rejects_invalid_items_without_overwriting_existing_list(
    tmp_path,
    arguments: dict[str, object],
    message: str,
) -> None:
    repository = JsonFileTodoRepository(tmp_path / "todos")
    original = TodoSnapshot.create(
        todo_list_id="default",
        todos=(TodoItem(content="保留原清单", status=TodoStatus.PENDING),),
    )
    repository.replace(original)
    tool = TodoWriteTool(repository)

    with pytest.raises(ToolValidationError, match=message):
        tool.run(arguments)

    assert repository.load("default") == original


def test_todo_write_declares_the_complete_nested_parameter_schema(tmp_path) -> None:
    definition = TodoWriteTool(JsonFileTodoRepository(tmp_path / "todos")).definition

    assert definition.name == "todo_write"
    assert definition.tags == ("planning", "state")
    assert definition.parameters["required"] == ["todos"]
    item_schema = definition.parameters["properties"]["todos"]["items"]
    assert item_schema["required"] == ["content", "status"]
