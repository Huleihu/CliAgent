"""任务系统工具依赖的应用服务端口校验。"""

from local_dev_agent.tasks import TaskApplicationService


_REQUIRED_METHOD_NAMES = (
    "create_task",
    "list_tasks",
    "get_task",
    "claim_task",
    "complete_task",
)


def require_task_application_service(service: object) -> TaskApplicationService:
    """验证工具拿到完整应用用例端口，避免直接依赖 JSON 仓储。"""

    if not all(callable(getattr(service, method_name, None)) for method_name in _REQUIRED_METHOD_NAMES):
        raise TypeError("任务应用服务必须提供创建、查询、认领和完成方法。")
    return service  # type: ignore[return-value]
