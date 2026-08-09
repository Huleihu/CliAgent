from pathlib import Path

from local_dev_agent.tools import ToolExecutionContext
from local_dev_agent.tools.builtin import EditFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from local_dev_agent.tools.workspace import InMemoryRunWorkingDirectoryRegistry


def _context(run_id: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=f"session-{run_id}",
        run_id=run_id,
        step_id=f"step-{run_id}",
    )


def test_file_tools_isolate_alice_and_bob_runs_without_changing_main_workspace(
    tmp_path: Path,
) -> None:
    main_workspace = tmp_path / "main"
    alice_workspace = main_workspace / ".worktrees" / "api-login"
    bob_workspace = main_workspace / ".worktrees" / "api-report"
    for workspace in (main_workspace, alice_workspace, bob_workspace):
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "status.txt").write_text("待办", encoding="utf-8")
    registry = InMemoryRunWorkingDirectoryRegistry(main_workspace=main_workspace)
    registry.bind(run_id="run-alice", directory=alice_workspace)
    registry.bind(run_id="run-bob", directory=bob_workspace)

    write_file = WriteFileTool(main_workspace, working_directory_resolver=registry)
    edit_file = EditFileTool(main_workspace, working_directory_resolver=registry)
    read_file = ReadFileTool(main_workspace, working_directory_resolver=registry)
    list_files = ListFilesTool(main_workspace, working_directory_resolver=registry)

    write_file.run({"path": "alice.txt", "content": "Alice 的改动"}, context=_context("run-alice"))
    write_file.run({"path": "bob.txt", "content": "Bob 的改动"}, context=_context("run-bob"))
    edit_file.run(
        {"path": "status.txt", "old_text": "待办", "new_text": "Alice 处理中"},
        context=_context("run-alice"),
    )

    assert not (main_workspace / "alice.txt").exists()
    assert not (main_workspace / "bob.txt").exists()
    assert (alice_workspace / "alice.txt").read_text(encoding="utf-8") == "Alice 的改动"
    assert (bob_workspace / "bob.txt").read_text(encoding="utf-8") == "Bob 的改动"
    assert (alice_workspace / "status.txt").read_text(encoding="utf-8") == "Alice 处理中"
    assert (bob_workspace / "status.txt").read_text(encoding="utf-8") == "待办"
    assert read_file.run({"path": "bob.txt"}, context=_context("run-bob"))["content"] == "Bob 的改动"
    assert list_files.run({"pattern": "*.txt"}, context=_context("run-alice"))["files"] == [
        "alice.txt",
        "status.txt",
    ]


def test_registry_returns_main_workspace_for_unbound_or_released_runs(tmp_path: Path) -> None:
    main_workspace = tmp_path / "main"
    isolated_workspace = main_workspace / ".worktrees" / "api-login"
    isolated_workspace.mkdir(parents=True)
    registry = InMemoryRunWorkingDirectoryRegistry(main_workspace=main_workspace)

    assert registry.resolve(context=None) == main_workspace.resolve()
    assert registry.resolve(context=_context("run-main")) == main_workspace.resolve()
    registry.bind(run_id="run-alice", directory=isolated_workspace)
    assert registry.resolve(context=_context("run-alice")) == isolated_workspace.resolve()
    registry.release(run_id="run-alice")
    assert registry.resolve(context=_context("run-alice")) == main_workspace.resolve()
