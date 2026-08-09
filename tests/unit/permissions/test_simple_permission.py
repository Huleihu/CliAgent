from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from local_dev_agent.hooks import (
    HookEvent,
    HookRegistry,
    HookRunner,
)
from local_dev_agent.permissions import (
    McpPermissionPolicy,
    PermissionContext,
    PermissionDecision,
    PermissionHook,
    PermissionResult,
    SimplePermissionPolicy,
    ask_user,
)
from local_dev_agent.mcp import McpToolAnnotations
from local_dev_agent.tools import (
    FakeTool,
    ToolCallRequest,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)


def _context(name: str, arguments: dict[str, object]) -> PermissionContext:
    return PermissionContext(
        session_id="session-1",
        run_id="run-1",
        step_id="step-1",
        request=ToolCallRequest(
            name=name,
            arguments=arguments,
            call_id="toolu-1",
        ),
    )


def _bash_definition() -> ToolDefinition:
    return ToolDefinition(
        name="bash",
        description="执行测试命令。",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )


def test_permission_result_has_strict_allow_and_deny_semantics() -> None:
    assert PermissionResult.allow().decision is PermissionDecision.ALLOW
    assert PermissionResult.deny("测试拒绝。").reason == "测试拒绝。"

    with pytest.raises(ValueError, match="不能附带拒绝原因"):
        PermissionResult(PermissionDecision.ALLOW, "多余原因")
    with pytest.raises(ValueError, match="必须是非空字符串"):
        PermissionResult.deny(" ")


def test_permission_context_is_immutable() -> None:
    context = _context("read_file", {"path": "README.md"})

    with pytest.raises(FrozenInstanceError):
        context.run_id = "other-run"  # type: ignore[misc]
    with pytest.raises(TypeError):
        context.request.arguments["path"] = "other.md"  # type: ignore[index]


def test_simple_policy_allows_calls_that_match_no_permission_rule(
    tmp_path: Path,
) -> None:
    approvals: list[str] = []
    policy = SimplePermissionPolicy(
        tmp_path,
        approval_prompt=lambda context, reason: approvals.append(reason) or False,
    )

    result = policy.check(_context("read_file", {"path": "README.md"}))

    assert result == PermissionResult.allow()
    assert approvals == []


def test_simple_policy_hard_denies_before_asking_user(tmp_path: Path) -> None:
    approvals: list[str] = []
    policy = SimplePermissionPolicy(
        tmp_path,
        approval_prompt=lambda context, reason: approvals.append(reason) or True,
    )

    result = policy.check(_context("bash", {"command": "sudo reboot"}))

    assert result.decision is PermissionDecision.DENY
    assert "sudo" in result.reason  # type: ignore[operator]
    assert approvals == []


@pytest.mark.parametrize(
    ("approved", "expected_decision"),
    [
        (True, PermissionDecision.ALLOW),
        (False, PermissionDecision.DENY),
    ],
)
def test_simple_policy_asks_for_risky_bash_commands(
    tmp_path: Path,
    approved: bool,
    expected_decision: PermissionDecision,
) -> None:
    approval_requests: list[tuple[str, str]] = []

    def approve(context: PermissionContext, reason: str) -> bool:
        approval_requests.append((context.request.name, reason))
        return approved

    result = SimplePermissionPolicy(
        tmp_path,
        approval_prompt=approve,
    ).check(_context("bash", {"command": "rm temporary.txt"}))

    assert result.decision is expected_decision
    assert approval_requests == [("bash", "命令可能执行破坏性操作。")]


def test_simple_policy_asks_before_writing_outside_workspace(
    tmp_path: Path,
) -> None:
    reasons: list[str] = []
    outside_path = tmp_path.parent / "outside.txt"
    policy = SimplePermissionPolicy(
        tmp_path,
        approval_prompt=lambda context, reason: reasons.append(reason) or False,
    )

    result = policy.check(
        _context("write_file", {"path": str(outside_path), "content": "测试"})
    )

    assert result.decision is PermissionDecision.DENY
    assert reasons == ["工具将写入工作区之外。"]


class _McpAnnotationsCatalog:
    def __init__(self, annotations: dict[str, McpToolAnnotations]) -> None:
        self._annotations = annotations

    def get_annotations(self, public_tool_name: str) -> McpToolAnnotations | None:
        return self._annotations.get(public_tool_name)


def test_mcp_policy_requires_confirmation_for_connect_and_external_tools(tmp_path: Path) -> None:
    reasons: list[str] = []
    policy = McpPermissionPolicy(
        SimplePermissionPolicy(tmp_path),
        _McpAnnotationsCatalog(
            {
                "mcp__docs__search": McpToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    open_world_hint=False,
                ),
                "mcp__jira__create_issue": McpToolAnnotations(
                    destructive_hint=True,
                    open_world_hint=True,
                ),
            }
        ),
        approval_prompt=lambda _context, reason: reasons.append(reason) or False,
    )

    connect_result = policy.check(_context("connect_mcp", {"name": "docs"}))
    docs_result = policy.check(_context("mcp__docs__search", {"query": "S19"}))
    jira_result = policy.check(
        _context("mcp__jira__create_issue", {"summary": "修复登录"})
    )
    local_result = policy.check(_context("read_file", {"path": "README.md"}))

    assert all(
        result.decision is PermissionDecision.DENY
        for result in (connect_result, docs_result, jira_result)
    )
    assert local_result == PermissionResult.allow()
    assert "加入当前 Lead 工具池" in reasons[0]
    assert "声明为只读操作" in reasons[1]
    assert "可能执行破坏性操作" in reasons[2]
    assert "可能访问或影响外部系统" in reasons[2]


def test_mcp_policy_blocks_external_tool_through_existing_permission_hook(tmp_path: Path) -> None:
    tool = FakeTool(
        definition=ToolDefinition(
            name="mcp__jira__create_issue",
            description="创建外部工单。",
            parameters={"type": "object", "properties": {}},
        ),
        result={},
    )
    registry = ToolRegistry()
    registry.register(tool)
    hooks = HookRegistry()
    hooks.register(
        HookEvent.PRE_TOOL_USE,
        PermissionHook(
            McpPermissionPolicy(
                SimplePermissionPolicy(tmp_path),
                _McpAnnotationsCatalog(
                    {"mcp__jira__create_issue": McpToolAnnotations(destructive_hint=True)}
                ),
                approval_prompt=lambda _context, _reason: False,
            )
        ),
    )

    result = ToolExecutor(registry, hook_runner=HookRunner(hooks)).execute(
        ToolCallRequest(name="mcp__jira__create_issue", arguments={}, call_id="toolu-1"),
        context=ToolExecutionContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            call_id="toolu-1",
        ),
    )

    assert result.success is False
    assert result.error["type"] == "ToolHookBlockedError"  # type: ignore[index]
    assert tool.calls == []


def test_permission_hook_blocks_tool_execution_when_user_denies(
    tmp_path: Path,
) -> None:
    tool = FakeTool(definition=_bash_definition(), result={"output": "已执行"})
    tool_registry = ToolRegistry()
    tool_registry.register(tool)
    hook_registry = HookRegistry()
    hook_registry.register(
        HookEvent.PRE_TOOL_USE,
        PermissionHook(
            SimplePermissionPolicy(
                tmp_path,
                approval_prompt=lambda context, reason: False,
            )
        ),
    )
    request = ToolCallRequest(
        name="bash",
        arguments={"command": "rm temporary.txt"},
        call_id="toolu-1",
    )

    result = ToolExecutor(
        tool_registry,
        hook_runner=HookRunner(hook_registry),
    ).execute(
        request,
        context=ToolExecutionContext(
            session_id="session-1",
            run_id="run-1",
            step_id="step-1",
            call_id=request.call_id,
        ),
    )

    assert result.success is False
    assert result.error["type"] == "ToolHookBlockedError"  # type: ignore[index]
    assert "用户拒绝执行" in result.error["message"]  # type: ignore[index]
    assert result.call_id == "toolu-1"
    assert tool.calls == []


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("y", True), ("yes", True), ("", False), ("n", False)],
)
def test_console_approval_defaults_to_deny(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: str,
    expected: bool,
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    context = _context("bash", {"command": "rm temporary.txt"})

    result = ask_user(context, "命令可能执行破坏性操作。")

    assert result is expected
    output = capsys.readouterr().out
    assert "命令可能执行破坏性操作" in output
    assert "bash" in output
