import pytest

from local_dev_agent.tasks import Task, TaskStatus
from local_dev_agent.tasks.json_codec import decode_task, encode_task


def _task() -> Task:
    return Task(
        task_id="task-api",
        subject="实现 API。",
        description="新增登录端点。",
        status=TaskStatus.IN_PROGRESS,
        owner="agent-api",
        blocked_by=("task-schema",),
        worktree="api-login",
    )


def test_encode_task_builds_a_versioned_json_envelope() -> None:
    assert encode_task(_task()) == {
        "schema_version": 1,
        "entity_type": "task",
        "state": {
            "task_id": "task-api",
            "subject": "实现 API。",
            "description": "新增登录端点。",
            "status": "in_progress",
            "owner": "agent-api",
            "blocked_by": ["task-schema"],
            "worktree": "api-login",
        },
    }


def test_decode_task_recovers_an_equivalent_immutable_snapshot() -> None:
    assert decode_task(encode_task(_task())) == _task()


def test_decode_task_defaults_a_pre_s18_snapshot_to_an_unbound_worktree() -> None:
    payload = encode_task(_task())
    payload["state"].pop("worktree")  # type: ignore[index]

    decoded = decode_task(payload)

    assert decoded.worktree is None
    assert decoded.task_id == "task-api"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": 2, "entity_type": "task", "state": {}},
        {"schema_version": 1, "entity_type": "todo_list", "state": {}},
        {"schema_version": 1, "entity_type": "task", "state": []},
    ],
)
def test_decode_task_rejects_an_unsupported_envelope(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="任务文件结构不受支持"):
        decode_task(payload)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("task_id", "", "task_id”必须是非空字符串"),
        ("subject", None, "subject”必须是字符串"),
        ("description", None, "description”必须是字符串"),
        ("owner", "", "owner”必须是非空字符串或空值"),
        ("worktree", "", "worktree”必须是非空字符串或空值"),
        ("blocked_by", "task-schema", "blocked_by”必须是字符串列表"),
    ],
)
def test_decode_task_rejects_invalid_field_shapes(
    field_name: str,
    value: object,
    message: str,
) -> None:
    payload = encode_task(_task())
    payload["state"][field_name] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        decode_task(payload)


def test_decode_task_rejects_an_unknown_status() -> None:
    payload = encode_task(_task())
    payload["state"]["status"] = "paused"  # type: ignore[index]

    with pytest.raises(ValueError, match="status”必须是 pending、in_progress 或 completed"):
        decode_task(payload)
