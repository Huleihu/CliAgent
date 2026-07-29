from local_dev_agent.tasks import Task, TaskRepository


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

    repository: TaskRepository = FakeTaskRepository()

    assert repository.add(task) is task
    assert repository.get("task-1") is task
