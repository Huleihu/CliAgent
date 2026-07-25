"""S06 子 Agent 委派任务与结果的不可变领域契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable
from uuid import uuid4


def _require_nonempty_text(field_name: str, value: str) -> None:
    """拒绝无法关联、执行或展示的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


def _require_text_tuple(field_name: str, value: tuple[str, ...]) -> None:
    """限制多值文本使用不可变快照，并拒绝其中的空白条目。"""

    if not isinstance(value, tuple) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"字段“{field_name}”必须是非空字符串元组。")


class SubagentOutcome(StrEnum):
    """子 Agent 一次有界执行结束后的结果分类。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class SubagentTask:
    """父 Agent 显式交给独立子上下文的一项有界任务。"""

    task_id: str
    parent_session_id: str
    parent_run_id: str
    parent_step_id: str
    description: str
    acceptance_criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """保证任务可追溯，并冻结父 Agent 明确传递的最小上下文。"""

        _require_nonempty_text("task_id", self.task_id)
        _require_nonempty_text("parent_session_id", self.parent_session_id)
        _require_nonempty_text("parent_run_id", self.parent_run_id)
        _require_nonempty_text("parent_step_id", self.parent_step_id)
        _require_nonempty_text("description", self.description)
        _require_text_tuple("acceptance_criteria", self.acceptance_criteria)

    @classmethod
    def create(
        cls,
        *,
        parent_session_id: str,
        parent_run_id: str,
        parent_step_id: str,
        description: str,
        acceptance_criteria: Iterable[str] = (),
        task_id: str | None = None,
    ) -> "SubagentTask":
        """创建任务并复制验收标准，避免调用方继续修改输入集合。"""

        return cls(
            task_id=task_id or str(uuid4()),
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            parent_step_id=parent_step_id,
            description=description,
            acceptance_criteria=tuple(acceptance_criteria),
        )


@dataclass(frozen=True, slots=True)
class SubagentResult:
    """子 Agent 返回父 Agent 的结构化、可追溯最小结果。"""

    task_id: str
    outcome: SubagentOutcome
    summary: str
    child_session_id: str
    child_run_id: str
    evidence: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    unresolved_risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """拒绝含糊结果，避免父 Agent 将缺少关联或摘要的返回视为完成。"""

        _require_nonempty_text("task_id", self.task_id)
        if not isinstance(self.outcome, SubagentOutcome):
            raise ValueError("子 Agent 结果状态必须是 SubagentOutcome 枚举值。")
        _require_nonempty_text("summary", self.summary)
        _require_nonempty_text("child_session_id", self.child_session_id)
        _require_nonempty_text("child_run_id", self.child_run_id)
        _require_text_tuple("evidence", self.evidence)
        _require_text_tuple("artifacts", self.artifacts)
        _require_text_tuple("unresolved_risks", self.unresolved_risks)

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        outcome: SubagentOutcome,
        summary: str,
        child_session_id: str,
        child_run_id: str,
        evidence: Iterable[str] = (),
        artifacts: Iterable[str] = (),
        unresolved_risks: Iterable[str] = (),
    ) -> "SubagentResult":
        """创建结果并复制集合字段，隔离运行器内部的可变数据。"""

        return cls(
            task_id=task_id,
            outcome=outcome,
            summary=summary,
            child_session_id=child_session_id,
            child_run_id=child_run_id,
            evidence=tuple(evidence),
            artifacts=tuple(artifacts),
            unresolved_risks=tuple(unresolved_risks),
        )
