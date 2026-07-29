import json

import pytest

from local_dev_agent.tasks import (
    CorruptedTaskFileError,
    JsonFileTaskRepository,
    Task,
    TaskAlreadyExistsError,
    TaskNotFoundError,
    TaskStatus,
)


def _pending_task(task_id: str) -> Task:
    return Task.create(task_id=task_id, subject=f"{task_id} 的任务。")


def _in_progress_task(task_id: str) -> Task:
    return Task(
        task_id=task_id,
        subject=f"{task_id} 的任务。",
        description="开始执行。",
        status=TaskStatus.IN_PROGRESS,
        owner="agent-a",
    )


def test_repository_returns_empty_results_before_any_task_is_saved(tmp_path) -> None:
    repository = JsonFileTaskRepository(tmp_path / "tasks")

    assert repository.get("task-1") is None
    assert repository.list() == ()


def test_repository_add_persists_a_task_for_another_instance(tmp_path) -> None:
    root_directory = tmp_path / "tasks"
    task = _pending_task("task-1")

    assert JsonFileTaskRepository(root_directory).add(task) is task

    persisted = JsonFileTaskRepository(root_directory).get("task-1")
    assert persisted == task
    payload = json.loads((root_directory / "task-1.json").read_text(encoding="utf-8"))
    assert payload["state"]["task_id"] == "task-1"


def test_repository_rejects_duplicate_additions(tmp_path) -> None:
    repository = JsonFileTaskRepository(tmp_path / "tasks")
    repository.add(_pending_task("task-1"))

    with pytest.raises(TaskAlreadyExistsError, match="task-1.*已存在"):
        repository.add(_pending_task("task-1"))


def test_repository_replace_updates_an_existing_task(tmp_path) -> None:
    repository = JsonFileTaskRepository(tmp_path / "tasks")
    repository.add(_pending_task("task-1"))
    replacement = _in_progress_task("task-1")

    assert repository.replace(replacement) is replacement
    assert repository.get("task-1") == replacement


def test_repository_replace_rejects_a_missing_task(tmp_path) -> None:
    repository = JsonFileTaskRepository(tmp_path / "tasks")

    with pytest.raises(TaskNotFoundError, match="task-1.*不存在"):
        repository.replace(_pending_task("task-1"))


def test_repository_lists_tasks_by_stable_file_name_order(tmp_path) -> None:
    repository = JsonFileTaskRepository(tmp_path / "tasks")
    repository.add(_pending_task("task-z"))
    repository.add(_pending_task("task-a"))

    assert tuple(task.task_id for task in repository.list()) == ("task-a", "task-z")


@pytest.mark.parametrize("content", ("{", "[]"))
def test_repository_wraps_invalid_json_as_a_corrupted_file_error(tmp_path, content: str) -> None:
    root_directory = tmp_path / "tasks"
    root_directory.mkdir()
    path = root_directory / "task-1.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(CorruptedTaskFileError, match="任务文件.*已损坏"):
        JsonFileTaskRepository(root_directory).get("task-1")


def test_repository_rejects_a_file_whose_task_id_does_not_match_its_name(tmp_path) -> None:
    root_directory = tmp_path / "tasks"
    root_directory.mkdir()
    (root_directory / "task-1.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entity_type": "task",
                "state": {
                    "task_id": "task-2",
                    "subject": "错误任务。",
                    "description": "",
                    "status": "pending",
                    "owner": None,
                    "blocked_by": [],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorruptedTaskFileError, match="任务文件.*已损坏"):
        JsonFileTaskRepository(root_directory).list()


@pytest.mark.parametrize("task_id", ("../task-1", "nested/task-1", "nested\\task-1"))
def test_repository_rejects_path_like_task_ids(tmp_path, task_id: str) -> None:
    repository = JsonFileTaskRepository(tmp_path / "tasks")
    task = _pending_task(task_id)

    with pytest.raises(ValueError, match="任务标识不能包含路径分隔符"):
        repository.add(task)
