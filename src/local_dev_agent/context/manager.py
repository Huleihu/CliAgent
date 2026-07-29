"""按固定顺序装配有预算的派生模型上下文。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .artifacts import ToolResultArtifact
from .budget import (
    ContextBudget,
    ContextBudgetEstimator,
    ContextBudgetReport,
    ContextInputSnapshot,
    Utf8ByteContextBudgetEstimator,
)
from .checkpoint_service import HistorySummaryCheckpointService
from .enrichment import ContextInputSnapshotEnricher
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
        history_summary_checkpoint_service: HistorySummaryCheckpointService | None = None,
        checkpoint_tail_message_count: int = 10,
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
        if history_summary_checkpoint_service is not None and (
            not hasattr(history_summary_checkpoint_service, "restore_view")
            or not hasattr(history_summary_checkpoint_service, "rebuild_view_from_full_history")
        ):
            raise ValueError(
                "history_summary_checkpoint_service 必须提供 restore_view 和 "
                "rebuild_view_from_full_history 方法。"
            )
        if (
            isinstance(checkpoint_tail_message_count, bool)
            or not isinstance(checkpoint_tail_message_count, int)
            or checkpoint_tail_message_count < 1
        ):
            raise ValueError("checkpoint_tail_message_count 必须是正整数。")
        self._budget = budget
        self._tool_result_budget_compactor = tool_result_budget_compactor
        self._history_summary_compactor = history_summary_compactor
        self._estimator = estimator or Utf8ByteContextBudgetEstimator()
        self._snip_compactor = snip_compactor or ConversationSnipCompactor()
        self._micro_compactor = micro_compactor or ToolResultMicroCompactor()
        self._history_summary_checkpoint_service = history_summary_checkpoint_service
        self._checkpoint_tail_message_count = checkpoint_tail_message_count

    def prepare(
        self,
        snapshot: ContextInputSnapshot,
        *,
        force_history_compaction: bool = False,
        context_enricher: ContextInputSnapshotEnricher | None = None,
        max_output_tokens: int | None = None,
    ) -> ContextPackage:
        """按 Artifact 化、L1、L2、预算复算、L4 的顺序装配请求视图。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        if not isinstance(force_history_compaction, bool):
            raise ValueError("字段“force_history_compaction”必须是布尔值。")
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ValueError("字段“max_output_tokens”必须是正整数。")
        if context_enricher is not None and not hasattr(context_enricher, "enrich"):
            raise ValueError("context_enricher 必须提供 enrich 方法。")
        budget = (
            replace(self._budget, max_output_tokens=max_output_tokens)
            if max_output_tokens is not None
            else self._budget
        )
        checkpoint_view = self._restore_checkpoint_view(snapshot)
        prepared_snapshot, budget_report, artifacts = self._prepare_pre_summary(
            checkpoint_view,
            budget=budget,
            context_enricher=context_enricher,
        )
        history_compacted = checkpoint_view is not snapshot
        if force_history_compaction or budget_report.exceeds_budget:
            history_compacted = True
            if self._history_summary_checkpoint_service is not None:
                rebuilt_view = self._history_summary_checkpoint_service.rebuild_view_from_full_history(
                    snapshot,
                    desired_covered_message_count=self._desired_checkpoint_coverage_count(
                        snapshot
                    ),
                )
                prepared_snapshot, budget_report, artifacts = self._prepare_pre_summary(
                    rebuilt_view,
                    budget=budget,
                    context_enricher=context_enricher,
                )
            else:
                summary_source = (
                    checkpoint_view
                    if context_enricher is not None
                    else prepared_snapshot
                )
                summarized_snapshot = self._history_summary_compactor.compact(
                    summary_source
                )
                prepared_snapshot, budget_report, artifacts = self._prepare_pre_summary(
                    summarized_snapshot,
                    budget=budget,
                    context_enricher=context_enricher,
                )
        if budget_report.exceeds_budget:
            raise ContextBudgetExceededError("历史摘要后上下文仍超过输入预算。")
        return ContextPackage(
            snapshot=prepared_snapshot,
            budget_report=budget_report,
            artifacts=artifacts,
            history_compacted=history_compacted,
        )

    def _restore_checkpoint_view(
        self,
        snapshot: ContextInputSnapshot,
    ) -> ContextInputSnapshot:
        """优先复用可信检查点；缺失检查点时保持完整原始快照。"""

        if self._history_summary_checkpoint_service is None:
            return snapshot
        return self._history_summary_checkpoint_service.restore_view(snapshot)

    def _prepare_pre_summary(
        self,
        snapshot: ContextInputSnapshot,
        *,
        budget: ContextBudget,
        context_enricher: ContextInputSnapshotEnricher | None,
    ) -> tuple[
        ContextInputSnapshot,
        ContextBudgetReport,
        tuple[ToolResultArtifact, ...],
    ]:
        """在摘要决策前执行既有 Artifact、L1、L2 与预算估算管线。"""

        enriched_snapshot = (
            context_enricher.enrich(snapshot)
            if context_enricher is not None
            else snapshot
        )
        budget_result = self._tool_result_budget_compactor.compact(enriched_snapshot)
        prepared_snapshot = self._snip_compactor.compact(budget_result.snapshot)
        prepared_snapshot = self._micro_compactor.compact(prepared_snapshot)
        return (
            prepared_snapshot,
            self._estimator.estimate(prepared_snapshot, budget),
            budget_result.artifacts,
        )

    def _desired_checkpoint_coverage_count(
        self,
        snapshot: ContextInputSnapshot,
    ) -> int:
        """保留最近原始尾部消息；短历史沿用既有 L4 的全历史摘要语义。"""

        if len(snapshot.messages) <= self._checkpoint_tail_message_count:
            return len(snapshot.messages)
        return len(snapshot.messages) - self._checkpoint_tail_message_count
