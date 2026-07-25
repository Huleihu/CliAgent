from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from local_dev_agent.subagents import (
    SubagentOutcome,
    SubagentResult,
    SubagentRunner,
    SubagentTask,
)


def _task() -> SubagentTask:
    return SubagentTask.create(
        task_id="task-1",
        parent_session_id="session-parent",
        parent_run_id="run-parent",
        parent_step_id="step-parent",
        description="定位配置加载失败的原因。",
        acceptance_criteria=("给出根因", "列出相关文件"),
    )


def test_outcomes_expose_stable_values() -> None:
    assert [outcome.value for outcome in SubagentOutcome] == [
        "succeeded",
        "failed",
        "exhausted",
    ]


def test_task_create_preserves_parent_links_and_copies_acceptance_criteria() -> None:
    criteria = ["给出根因", "列出相关文件"]

    task = SubagentTask.create(
        task_id="task-1",
        parent_session_id="session-parent",
        parent_run_id="run-parent",
        parent_step_id="step-parent",
        description="定位配置加载失败的原因。",
        acceptance_criteria=criteria,
    )
    criteria.clear()

    assert task.task_id == "task-1"
    assert task.parent_session_id == "session-parent"
    assert task.parent_run_id == "run-parent"
    assert task.parent_step_id == "step-parent"
    assert task.description == "定位配置加载失败的原因。"
    assert task.acceptance_criteria == ("给出根因", "列出相关文件")


def test_task_create_generates_a_uuid_when_id_is_omitted() -> None:
    task = SubagentTask.create(
        parent_session_id="session-parent",
        parent_run_id="run-parent",
        parent_step_id="step-parent",
        description="检查测试框架。",
    )

    assert str(UUID(task.task_id)) == task.task_id


@pytest.mark.parametrize(
    "field_name",
    [
        "task_id",
        "parent_session_id",
        "parent_run_id",
        "parent_step_id",
        "description",
    ],
)
def test_task_rejects_blank_required_text(field_name: str) -> None:
    values = {
        "task_id": "task-1",
        "parent_session_id": "session-parent",
        "parent_run_id": "run-parent",
        "parent_step_id": "step-parent",
        "description": "检查测试框架。",
        "acceptance_criteria": (),
    }
    values[field_name] = " "

    with pytest.raises(ValueError, match=f"字段“{field_name}”必须是非空字符串"):
        SubagentTask(**values)


@pytest.mark.parametrize(
    "criteria",
    [
        ["列表不是冻结快照"],
        ("有效标准", ""),
        ("有效标准", 1),
    ],
)
def test_task_rejects_invalid_acceptance_criteria(criteria: object) -> None:
    with pytest.raises(
        ValueError,
        match="字段“acceptance_criteria”必须是非空字符串元组",
    ):
        SubagentTask(
            task_id="task-1",
            parent_session_id="session-parent",
            parent_run_id="run-parent",
            parent_step_id="step-parent",
            description="检查测试框架。",
            acceptance_criteria=criteria,  # type: ignore[arg-type]
        )


def test_result_create_copies_structured_return_collections() -> None:
    evidence = ["tests/unit/test_main.py 使用 pytest"]
    artifacts = ["reports/testing.md"]
    risks = ["尚未运行集成测试"]

    result = SubagentResult.create(
        task_id="task-1",
        outcome=SubagentOutcome.SUCCEEDED,
        summary="项目使用 pytest。",
        child_session_id="session-child",
        child_run_id="run-child",
        evidence=evidence,
        artifacts=artifacts,
        unresolved_risks=risks,
    )
    evidence.clear()
    artifacts.clear()
    risks.clear()

    assert result.evidence == ("tests/unit/test_main.py 使用 pytest",)
    assert result.artifacts == ("reports/testing.md",)
    assert result.unresolved_risks == ("尚未运行集成测试",)


def test_result_preserves_non_success_outcome_and_trace_links() -> None:
    result = SubagentResult.create(
        task_id="task-1",
        outcome=SubagentOutcome.EXHAUSTED,
        summary="达到最大模型调用轮次，未完成调查。",
        child_session_id="session-child",
        child_run_id="run-child",
        unresolved_risks=("根因尚未确认",),
    )

    assert result.outcome is SubagentOutcome.EXHAUSTED
    assert result.child_session_id == "session-child"
    assert result.child_run_id == "run-child"


def test_result_rejects_an_unknown_outcome() -> None:
    with pytest.raises(ValueError, match="必须是 SubagentOutcome 枚举值"):
        SubagentResult.create(
            task_id="task-1",
            outcome="succeeded",  # type: ignore[arg-type]
            summary="完成。",
            child_session_id="session-child",
            child_run_id="run-child",
        )


@pytest.mark.parametrize(
    "field_name",
    ["task_id", "summary", "child_session_id", "child_run_id"],
)
def test_result_rejects_blank_required_text(field_name: str) -> None:
    values = {
        "task_id": "task-1",
        "outcome": SubagentOutcome.SUCCEEDED,
        "summary": "完成。",
        "child_session_id": "session-child",
        "child_run_id": "run-child",
    }
    values[field_name] = " "

    with pytest.raises(ValueError, match=f"字段“{field_name}”必须是非空字符串"):
        SubagentResult.create(**values)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("evidence", ["列表不是冻结快照"]),
        ("artifacts", ("有效路径", " ")),
        ("unresolved_risks", ("有效风险", object())),
    ],
)
def test_result_rejects_invalid_collection_fields(
    field_name: str,
    value: object,
) -> None:
    values = {
        "task_id": "task-1",
        "outcome": SubagentOutcome.SUCCEEDED,
        "summary": "完成。",
        "child_session_id": "session-child",
        "child_run_id": "run-child",
        field_name: value,
    }

    with pytest.raises(
        ValueError,
        match=f"字段“{field_name}”必须是非空字符串元组",
    ):
        SubagentResult(**values)


def test_contracts_cannot_be_mutated_directly() -> None:
    task = _task()
    result = SubagentResult.create(
        task_id=task.task_id,
        outcome=SubagentOutcome.SUCCEEDED,
        summary="完成。",
        child_session_id="session-child",
        child_run_id="run-child",
    )

    with pytest.raises(FrozenInstanceError):
        task.description = "不能修改"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.summary = "不能修改"  # type: ignore[misc]


def test_runner_port_accepts_a_structural_implementation() -> None:
    expected = SubagentResult.create(
        task_id="task-1",
        outcome=SubagentOutcome.SUCCEEDED,
        summary="完成。",
        child_session_id="session-child",
        child_run_id="run-child",
    )

    class FakeSubagentRunner:
        def run(self, task: SubagentTask) -> SubagentResult:
            assert task.task_id == "task-1"
            return expected

    runner: SubagentRunner = FakeSubagentRunner()

    assert runner.run(_task()) is expected
