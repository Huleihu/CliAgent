"""任务系统工具结果的 JSON 原生值序列化。"""

from local_dev_agent.tasks import Task


def task_to_data(task: Task) -> dict[str, object]:
    """将不可变任务快照转换为可安全回填模型的 JSON 对象。"""

    return {
        "task_id": task.task_id,
        "subject": task.subject,
        "description": task.description,
        "status": task.status.value,
        "owner": task.owner,
        "blocked_by": list(task.blocked_by),
    }
