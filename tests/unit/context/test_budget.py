from dataclasses import FrozenInstanceError

import pytest

from local_dev_agent.context import (
    ContextBudget,
    ContextBudgetReport,
    ContextInputSnapshot,
    Utf8ByteContextBudgetEstimator,
)
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock, ToolResultBlock
from local_dev_agent.tools.schema import ToolDefinition


def _create_snapshot() -> ContextInputSnapshot:
    return ContextInputSnapshot(
        session_id=" session-1 ",
        run_id=" run-1 ",
        system_prompt="使用中文回答。",
        tools=(
            ToolDefinition(
                name="read_file",
                description="读取 UTF-8 文本文件。",
                parameters={"type": "object", "properties": {}},
            ),
        ),
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("读取 README.md。"),),
            ),
            ModelMessage(
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(
                        tool_use_id="toolu-1",
                        content={"content": "# 项目说明"},
                    ),
                ),
            ),
        ),
    )


def test_context_budget_calculates_available_input_tokens() -> None:
    budget = ContextBudget(
        context_window_tokens=32_000,
        max_output_tokens=8_000,
        safety_margin_tokens=4_000,
    )

    assert budget.available_input_tokens == 20_000


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {
                "context_window_tokens": 0,
                "max_output_tokens": 0,
                "safety_margin_tokens": 0,
            },
            "字段“context_window_tokens”必须大于零",
        ),
        (
            {
                "context_window_tokens": 10,
                "max_output_tokens": 6,
                "safety_margin_tokens": 4,
            },
            "必须保留至少一个输入 token",
        ),
        (
            {
                "context_window_tokens": True,
                "max_output_tokens": 0,
                "safety_margin_tokens": 0,
            },
            "字段“context_window_tokens”必须是非负整数",
        ),
    ],
)
def test_context_budget_rejects_invalid_boundaries(
    arguments: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ContextBudget(**arguments)


def test_input_snapshot_normalizes_identifiers_and_is_immutable() -> None:
    snapshot = _create_snapshot()

    assert snapshot.session_id == "session-1"
    assert snapshot.run_id == "run-1"
    with pytest.raises(FrozenInstanceError):
        snapshot.run_id = "run-2"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("session_id", " ", "字段“session_id”必须是非空字符串"),
        ("run_id", "", "字段“run_id”必须是非空字符串"),
        ("system_prompt", " ", "字段“system_prompt”必须是非空字符串"),
        ("messages", (), "字段“messages”必须是非空 ModelMessage 元组"),
    ],
)
def test_input_snapshot_rejects_invalid_required_values(
    field_name: str,
    value: object,
    message: str,
) -> None:
    arguments = {
        "session_id": "session-1",
        "run_id": "run-1",
        "messages": _create_snapshot().messages,
        "system_prompt": "系统提示。",
    }
    arguments[field_name] = value

    with pytest.raises(ValueError, match=message):
        ContextInputSnapshot(**arguments)


def test_estimator_returns_a_deterministic_partitioned_report() -> None:
    snapshot = _create_snapshot()
    budget = ContextBudget(
        context_window_tokens=32_000,
        max_output_tokens=8_000,
        safety_margin_tokens=4_000,
    )
    estimator = Utf8ByteContextBudgetEstimator()

    first = estimator.estimate(snapshot, budget)
    second = estimator.estimate(snapshot, budget)

    assert first == second
    assert first.system_prompt_tokens > 0
    assert first.tool_definition_tokens > 0
    assert first.message_tokens > 0
    assert first.estimated_input_tokens == (
        first.system_prompt_tokens
        + first.tool_definition_tokens
        + first.message_tokens
    )
    assert first.remaining_input_tokens == (
        budget.available_input_tokens - first.estimated_input_tokens
    )
    assert not first.exceeds_budget


def test_estimator_counts_utf8_content_and_detects_budget_exhaustion() -> None:
    snapshot = ContextInputSnapshot(
        session_id="session-1",
        run_id="run-1",
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(TextBlock("你" * 20),),
            ),
        ),
    )
    budget = ContextBudget(
        context_window_tokens=20,
        max_output_tokens=1,
        safety_margin_tokens=1,
    )

    report = Utf8ByteContextBudgetEstimator().estimate(snapshot, budget)

    assert report.message_tokens >= 15
    assert report.exceeds_budget
    assert report.remaining_input_tokens < 0


def test_budget_report_rejects_invalid_partition_values() -> None:
    with pytest.raises(ValueError, match="字段“message_tokens”必须是非负整数"):
        ContextBudgetReport(
            budget=ContextBudget(
                context_window_tokens=10,
                max_output_tokens=1,
                safety_margin_tokens=1,
            ),
            system_prompt_tokens=0,
            tool_definition_tokens=0,
            message_tokens=-1,
        )
