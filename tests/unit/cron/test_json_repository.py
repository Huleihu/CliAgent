import json
from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import (
    CorruptedCronTaskFileError,
    CronTask,
    CronTaskAlreadyExistsError,
    CronTaskNotFoundError,
    CronTaskScope,
    JsonFileCronTaskRepository,
)


def _task(task_id: str = "cron-001") -> CronTask:
    return CronTask.create(
        task_id=task_id,
        cron="0 9 * * 1-5",
        prompt="运行每日检查。",
        scope=CronTaskScope.DURABLE,
        created_at=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc),
    )


def test_json_repository_persists_reloads_replaces_and_removes_durable_tasks(tmp_path) -> None:
    repository = JsonFileCronTaskRepository(tmp_path / "cron")
    task = _task()

    assert repository.list_visible_to_session("session-001") == ()
    assert repository.add(task) is task
    reloaded = JsonFileCronTaskRepository(tmp_path / "cron")
    assert reloaded.get(task.task_id) == task
    marked = task.mark_enqueued(
        minute=datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
    )
    assert reloaded.replace(marked) is marked
    assert reloaded.remove(task.task_id) == marked
    assert reloaded.get(task.task_id) is None


def test_json_repository_skips_invalid_recovered_entries_without_executing_them(tmp_path) -> None:
    root = tmp_path / "cron"
    root.mkdir()
    path = root / "scheduled_tasks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entity_type": "cron_task_collection",
                "tasks": [
                    {
                        "task_id": "cron-valid",
                        "cron": "0 9 * * *",
                        "prompt": "运行检查。",
                        "recurring": True,
                        "scope": "durable",
                        "created_at": "2026-07-30T09:00:00+00:00",
                        "last_enqueued_minute": None,
                    },
                    {
                        "task_id": "cron-invalid",
                        "cron": "? * * * *",
                        "prompt": "不应恢复。",
                        "recurring": True,
                        "scope": "durable",
                        "created_at": "2026-07-30T09:00:00+00:00",
                        "last_enqueued_minute": None,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    tasks = JsonFileCronTaskRepository(root).list_visible_to_session("session-001")

    assert [task.task_id for task in tasks] == ["cron-valid"]


def test_json_repository_rejects_corrupted_collection_and_invalid_writes(tmp_path) -> None:
    repository = JsonFileCronTaskRepository(tmp_path / "cron")
    durable_task = _task()
    repository.add(durable_task)

    with pytest.raises(CronTaskAlreadyExistsError, match="cron-001.*已存在"):
        repository.add(durable_task)
    with pytest.raises(CronTaskNotFoundError, match="cron-missing.*不存在"):
        repository.replace(_task("cron-missing"))
    with pytest.raises(ValueError, match="只能保存 durable"):
        repository.add(
            CronTask.create(
                task_id="cron-session",
                cron="0 9 * * *",
                prompt="不应持久化。",
                owner_session_id="session-001",
            )
        )

    path = tmp_path / "corrupted" / "scheduled_tasks.json"
    path.parent.mkdir()
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(CorruptedCronTaskFileError, match="已损坏"):
        JsonFileCronTaskRepository(path.parent).list_visible_to_session("session-001")
