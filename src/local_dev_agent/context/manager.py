"""按固定顺序装配有预算的派生模型上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from .artifacts import ToolResultArtifact
from .budget import (
    ContextBudget,
    ContextBudgetEstimator,
    ContextBudgetReport,
    ContextInputSnapshot,
    Utf8ByteContextBudgetEstimator,
)
from .structural_compaction import ConversationSnipCompactor, ToolResultMicroCompactor
from .summary import HistorySummaryCompactor
from .tool_result_budget import ToolResultBudgetCompactor


class ContextBudgetExceededError(RuntimeError):
    """当历史摘要后仍无法装入输入预算时抛出。"""


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """一次模型调用实际使用的派生快照、预算报告和 Artifact 引用。"""

    snapshot: ContextInputSnapshot
    budget_report: ContextBudgetReport
    artifacts: tuple[ToolResultArtifact, ...]
    history_compacted: bool

    def __post_init__(self) -> None:
        """确保 Runtime 只接收已验证且处于预算内的请求包。"""

        if not isinstance(self.snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        if not isinstance(self.budget_report, ContextBudgetReport):
            raise ValueError("字段“budget_report”必须是 ContextBudgetReport 对象。")
        if not isinstance(self.artifacts, tuple) or not all(
            isinstance(artifact, ToolResultArtifact) for artifact in self.artifacts
        ):
            raise ValueError("字段“artifacts”必须是 ToolResultArtifact 元组。")
        if not isinstance(self.history_compacted, bool):
            raise ValueError("字段“history_compacted”必须是布尔值。")
        if self.budget_report.exceeds_budget:
            raise ValueError("上下文请求包不能超过输入预算。")


class ContextManager:
    """将大结果处理、结构裁剪和历史摘要组合为单一模型调用前边界。"""

    def __init__(
        self,
        budget: ContextBudget,
        tool_result_budget_compactor: ToolResultBudgetCompactor,
        history_summary_compactor: HistorySummaryCompactor,
        *,
        estimator: ContextBudgetEstimator | None = None,
        snip_compactor: ConversationSnipCompactor | None = None,
        micro_compactor: ToolResultMicroCompactor | None = None,
    ) -> None:
        if not isinstance(budget, ContextBudget):
            raise ValueError("字段“budget”必须是 ContextBudget 对象。")
        if not hasattr(tool_result_budget_compactor, "compact"):
            raise ValueError("tool_result_budget_compactor 必须提供 compact 方法。")
        if not hasattr(history_summary_compactor, "compact"):
            raise ValueError("history_summary_compactor 必须提供 compact 方法。")
        if estimator is not None and not hasattr(estimator, "estimate"):
            raise ValueError("estimator 必须提供 estimate 方法。")
        if snip_compactor is not None and not hasattr(snip_compactor, "compact"):
            raise ValueError("snip_compactor 必须提供 compact 方法。")
        if micro_compactor is not None and not hasattr(micro_compactor, "compact"):
            raise ValueError("micro_compactor 必须提供 compact 方法。")
        self._budget = budget
        self._tool_result_budget_compactor = tool_result_budget_compactor
        self._history_summary_compactor = history_summary_compactor
        self._estimator = estimator or Utf8ByteContextBudgetEstimator()
        self._snip_compactor = snip_compactor or ConversationSnipCompactor()
        self._micro_compactor = micro_compactor or ToolResultMicroCompactor()

    def prepare(self, snapshot: ContextInputSnapshot) -> ContextPackage:
        """按 Artifact 化、L1、L2、预算复算、L4 的顺序装配请求视图。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        budget_result = self._tool_result_budget_compactor.compact(snapshot)
        prepared_snapshot = self._snip_compactor.compact(budget_result.snapshot)
        prepared_snapshot = self._micro_compactor.compact(prepared_snapshot)
        budget_report = self._estimator.estimate(prepared_snapshot, self._budget)
        history_compacted = budget_report.exceeds_budget
        if history_compacted:
            prepared_snapshot = self._history_summary_compactor.compact(prepared_snapshot)
            budget_report = self._estimator.estimate(prepared_snapshot, self._budget)
        if budget_report.exceeds_budget:
            raise ContextBudgetExceededError("历史摘要后上下文仍超过输入预算。")
        return ContextPackage(
            snapshot=prepared_snapshot,
            budget_report=budget_report,
            artifacts=budget_result.artifacts,
            history_compacted=history_compacted,
        )
