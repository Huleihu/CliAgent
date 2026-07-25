"""子 Agent 执行能力的稳定端口。"""

from typing import Protocol

from .schema import SubagentResult, SubagentTask


class SubagentRunner(Protocol):
    """执行一项有界委派任务，不暴露具体模型、工具或持久化实现。"""

    def run(self, task: SubagentTask) -> SubagentResult:
        """运行独立子 Agent，并返回可由父 Agent 验收的结构化结果。"""
