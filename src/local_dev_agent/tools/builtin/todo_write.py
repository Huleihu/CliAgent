"""整体替换持久化待办清单的规划工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.todos import TodoItem, TodoRepository, TodoSnapshot, TodoStatus

from ..errors import ToolValidationError
from ..ports import Tool
from ..schema import ToolDefinition, ToolExecutionContext


class TodoWriteTool(Tool):
    """保存当前完整待办清单，不提供文件或命令执行能力。"""

    def __init__(self, repository: TodoRepository, *, todo_list_id: str = "default") -> None:
        self._repository = repository
        self._todo_list_id = todo_list_id
        self._definition = ToolDefinition(
            name="todo_write",
            description="整体更新当前持久化待办清单，用于追踪多步骤任务的执行进度。",
            parameters={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "当前完整待办清单；每次调用都会替换先前清单。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "待办事项的简短说明。",
                                },
                                "status": {
                                    "type": "string",
                                    "description": "进度状态：pending、in_progress 或 completed。",
                                },
                                "active_form": {
                                    "type": "string",
                                    "description": "可选的进行时说明，供后续界面展示。",
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
            tags=("planning", "state"),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回模型可见的静态工具定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """校验完整输入后原子替换清单，并返回紧凑进度统计。"""

        todos = self._read_todos(arguments)
        snapshot = TodoSnapshot.create(todo_list_id=self._todo_list_id, todos=todos)
        persisted = self._repository.replace(snapshot)
        return {
            "todo_list_id": persisted.todo_list_id,
            "total": len(persisted.todos),
            "pending": persisted.pending_count,
            "in_progress": persisted.in_progress_count,
            "completed": persisted.completed_count,
        }

    @staticmethod
    def _read_todos(arguments: Mapping[str, object]) -> tuple[TodoItem, ...]:
        """将工具协议字段转换为领域对象，确保失败时不写入仓储。"""

        value = arguments.get("todos")
        if not isinstance(value, list):
            raise ToolValidationError("字段“todos”必须是数组。")
        return tuple(
            TodoWriteTool._read_todo(item, index=index)
            for index, item in enumerate(value)
        )

    @staticmethod
    def _read_todo(value: object, *, index: int) -> TodoItem:
        """读取单个条目并为模型提供精确的字段错误。"""

        if not isinstance(value, Mapping):
            raise ToolValidationError(f"字段“todos[{index}]”必须是对象。")
        content = value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ToolValidationError(
                f"字段“todos[{index}].content”必须是非空字符串。"
            )
        status = value.get("status")
        if not isinstance(status, str):
            raise ToolValidationError(f"字段“todos[{index}].status”必须是字符串。")
        active_form = value.get("active_form")
        if "active_form" in value and (
            not isinstance(active_form, str) or not active_form.strip()
        ):
            raise ToolValidationError(
                f"字段“todos[{index}].active_form”必须是非空字符串。"
            )
        try:
            return TodoItem(
                content=content,
                status=TodoStatus(status),
                active_form=active_form,
            )
        except ValueError as error:
            raise ToolValidationError(
                f"字段“todos[{index}].status”必须是 pending、in_progress 或 completed。"
            ) from error
