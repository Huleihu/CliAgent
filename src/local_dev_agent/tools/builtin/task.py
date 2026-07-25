"""将父 Agent 的有界子任务委派给同步子 Agent 的工具。"""

from __future__ import annotations

from collections.abc import Mapping

from local_dev_agent.subagents.ports import SubagentRunner
from local_dev_agent.subagents.schema import SubagentTask

from ..errors import ToolExecutionError, ToolValidationError
from ..ports import Tool
from ..schema import DELEGATION_TOOL_TAG, ToolDefinition, ToolExecutionContext


class TaskTool(Tool):
    """创建可追溯子任务并将结构化结果回填给父 Agent。"""

    def __init__(self, runner: SubagentRunner) -> None:
        if not callable(getattr(runner, "run", None)):
            raise TypeError("子 Agent 运行器必须提供可调用的 run 方法。")
        self._runner = runner
        self._definition = ToolDefinition(
            name="task",
            description="委派一个有界子任务给独立子 Agent，并仅返回结构化结论。",
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "需要由子 Agent 独立完成的具体任务说明。",
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "description": "可选的验收标准列表。",
                        "items": {"type": "string"},
                    },
                },
                "required": ["description"],
            },
            tags=(DELEGATION_TOOL_TAG,),
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回父模型可见、但子目录默认不包含的委派工具定义。"""

        return self._definition

    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """从调用上下文构造子任务并返回不含中间消息的结果。"""

        if context is None:
            raise ToolExecutionError("task 工具必须在 ToolExecutionContext 中执行。")
        task = SubagentTask.create(
            parent_session_id=context.session_id,
            parent_run_id=context.run_id,
            parent_step_id=context.step_id,
            description=self._read_description(arguments),
            acceptance_criteria=self._read_acceptance_criteria(arguments),
        )
        result = self._runner.run(task)
        return {
            "task_id": result.task_id,
            "outcome": result.outcome.value,
            "summary": result.summary,
            "child_session_id": result.child_session_id,
            "child_run_id": result.child_run_id,
            "evidence": list(result.evidence),
            "artifacts": list(result.artifacts),
            "unresolved_risks": list(result.unresolved_risks),
        }

    @staticmethod
    def _read_description(arguments: Mapping[str, object]) -> str:
        """读取非空子任务说明，避免空任务消耗子 Agent 预算。"""

        description = arguments.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ToolValidationError("字段“description”必须是非空字符串。")
        return description

    @staticmethod
    def _read_acceptance_criteria(arguments: Mapping[str, object]) -> tuple[str, ...]:
        """将可选验收标准冻结为任务契约所需的文本元组。"""

        criteria = arguments.get("acceptance_criteria", [])
        if not isinstance(criteria, list) or not all(
            isinstance(item, str) and item.strip() for item in criteria
        ):
            raise ToolValidationError("字段“acceptance_criteria”必须是非空字符串数组。")
        return tuple(criteria)
