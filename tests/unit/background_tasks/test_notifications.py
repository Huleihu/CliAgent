from local_dev_agent.background_tasks import (
    BackgroundTask,
    BackgroundTaskNotificationSource,
    InMemoryBackgroundTaskRepository,
)


def _task(task_id: str, *, session_id: str = "session-001") -> BackgroundTask:
    return BackgroundTask.create(
        task_id=task_id,
        session_id=session_id,
        run_id="run-001",
        tool_call_id=f"toolu-{task_id}",
        command="python -m pytest <suite>",
    )


def test_notification_source_returns_each_terminal_task_once_with_escaped_text() -> None:
    repository = InMemoryBackgroundTaskRepository()
    completed = _task("bg_0001").complete(output_summary="3 < 5")
    failed = _task("bg_0002").fail(
        exit_code=2,
        output_summary="失败输出",
        failure_reason="命令包含 <参数>。",
    )
    repository.add(completed)
    repository.add(failed)
    source = BackgroundTaskNotificationSource(repository)

    notifications = source.drain(session_id="session-001")

    assert notifications == (
        "<task_notification>\n"
        "  <task_id>bg_0001</task_id>\n"
        "  <status>completed</status>\n"
        "  <command>python -m pytest &lt;suite&gt;</command>\n"
        "  <exit_code>0</exit_code>\n"
        "  <summary>3 &lt; 5</summary>\n"
        "  <failure_reason></failure_reason>\n"
        "</task_notification>",
        "<task_notification>\n"
        "  <task_id>bg_0002</task_id>\n"
        "  <status>failed</status>\n"
        "  <command>python -m pytest &lt;suite&gt;</command>\n"
        "  <exit_code>2</exit_code>\n"
        "  <summary>失败输出</summary>\n"
        "  <failure_reason>命令包含 &lt;参数&gt;。</failure_reason>\n"
        "</task_notification>",
    )
    assert source.drain(session_id="session-001") == ()


def test_notification_source_keeps_running_and_other_session_tasks_pending() -> None:
    repository = InMemoryBackgroundTaskRepository()
    running = _task("bg_0001")
    other_session = _task("bg_0002", session_id="session-002").complete(
        output_summary="完成"
    )
    repository.add(running)
    repository.add(other_session)
    source = BackgroundTaskNotificationSource(repository)

    assert source.drain(session_id="session-001") == ()
    assert "bg_0002" in source.drain(session_id="session-002")[0]
