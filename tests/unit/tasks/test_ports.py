from local_dev_agent.tasks import (
    AutonomousTaskBoard,
    Task,
    TaskRepository,
    TaskSnapshotReader,
    TaskWorktreeBinder,
)


def test_task_repository_port_accepts_a_structural_implementation() -> None:
    task = Task.create(task_id="task-1", subject="实现任务仓储。")

    class FakeTaskRepository:
        def __init__(self) -> None:
            self._tasks: dict[str, Task] = {}

        def add(self, task: Task) -> Task:
            self._tasks[task.task_id] = task
            return task

        def get(self, task_id: str) -> Task | None:
            return self._tasks.get(task_id)

        def list(self) -> tuple[Task, ...]:
            return tuple(self._tasks.values())

        def replace(self, task: Task) -> Task:
            self._tasks[task.task_id] = task
            return task

        def compare_and_replace(self, *, expected: Task, replacement: Task) -> bool:
            if self._tasks.get(expected.task_id) != expected:
                return False
            self._tasks[replacement.task_id] = replacement
            return True

    repository: TaskRepository = FakeTaskRepository()

    assert repository.add(task) is task
    assert repository.get("task-1") is task


def test_autonomous_task_board_port_accepts_a_structural_implementation() -> None:
    task = Task.create(task_id="task-1", subject="实现自主认领。")

    class FakeAutonomousTaskBoard:
        def list_claimable_tasks(self) -> tuple[Task, ...]:
            return (task,)

        def claim_next_task(self, *, owner: str) -> Task | None:
            return task if owner == "agent-a" else None

    board: AutonomousTaskBoard = FakeAutonomousTaskBoard()

    assert board.list_claimable_tasks() == (task,)
    assert board.claim_next_task(owner="agent-a") is task


def test_task_snapshot_reader_port_accepts_a_structural_implementation() -> None:
    task = Task.create(task_id="task-1", subject="读取任务快照。")

    class FakeTaskSnapshotReader:
        def get_task(self, task_id: str) -> Task:
            assert task_id == "task-1"
            return task

    reader: TaskSnapshotReader = FakeTaskSnapshotReader()

    assert reader.get_task("task-1") is task


def test_task_worktree_binder_port_accepts_a_structural_implementation() -> None:
    task = Task.create(task_id="task-1", subject="绑定工作树。")

    class FakeTaskWorktreeBinder:
        def bind_worktree(self, *, task_id: str, worktree: str) -> Task:
            assert task_id == "task-1"
            return Task(
                task_id=task.task_id,
                subject=task.subject,
                description=task.description,
                status=task.status,
                owner=task.owner,
                blocked_by=task.blocked_by,
                worktree=worktree,
            )

    binder: TaskWorktreeBinder = FakeTaskWorktreeBinder()

    assert binder.bind_worktree(task_id="task-1", worktree="api-login").worktree == "api-login"
