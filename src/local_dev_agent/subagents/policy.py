"""S06 子 Agent 的本地能力边界和执行预算。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DEFAULT_SUBAGENT_TOOL_NAMES = (
    "list_files",
    "read_file",
    "write_file",
    "edit_file",
)
"""子 Agent 默认可使用的工作区文件工具。"""

SUBAGENT_SYSTEM_PROMPT = """你是独立执行子任务的本地开发 Agent。

仅处理当前收到的任务，在完成后返回简洁、可供父 Agent 验收的结论。不得继续委派任务。"""
"""子 Agent 的稳定系统提示，不继承父对话内容。"""

_FORBIDDEN_TOOL_NAMES = frozenset({"task", "todo_write"})


def _require_nonempty_text(field_name: str, value: str) -> None:
    """拒绝无法用于预算、提示或工具匹配的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


@dataclass(frozen=True, slots=True)
class SubagentPolicy:
    """由应用装配决定的子 Agent 预算和工具白名单。"""

    max_turns: int = 10
    allowed_tool_names: tuple[str, ...] = DEFAULT_SUBAGENT_TOOL_NAMES
    system_prompt: str = SUBAGENT_SYSTEM_PROMPT

    def __post_init__(self) -> None:
        """在创建子循环前收束预算和能力，避免模型扩大可用权限。"""

        if isinstance(self.max_turns, bool) or not isinstance(self.max_turns, int):
            raise ValueError("字段“max_turns”必须是整数。")
        if self.max_turns < 1:
            raise ValueError("字段“max_turns”必须大于或等于 1。")
        if not isinstance(self.allowed_tool_names, tuple) or not all(
            isinstance(name, str) and name.strip() for name in self.allowed_tool_names
        ):
            raise ValueError("字段“allowed_tool_names”必须是非空字符串元组。")
        if len(set(self.allowed_tool_names)) != len(self.allowed_tool_names):
            raise ValueError("字段“allowed_tool_names”不能包含重复工具名称。")
        forbidden_names = sorted(_FORBIDDEN_TOOL_NAMES.intersection(self.allowed_tool_names))
        if forbidden_names:
            raise ValueError(
                "子 Agent 不允许使用工具：" + "、".join(forbidden_names) + "。"
            )
        _require_nonempty_text("system_prompt", self.system_prompt)

    @classmethod
    def create(
        cls,
        *,
        max_turns: int = 10,
        allowed_tool_names: Iterable[str] = DEFAULT_SUBAGENT_TOOL_NAMES,
        system_prompt: str = SUBAGENT_SYSTEM_PROMPT,
    ) -> "SubagentPolicy":
        """创建策略并复制白名单，隔离调用方后续的可变集合修改。"""

        return cls(
            max_turns=max_turns,
            allowed_tool_names=tuple(allowed_tool_names),
            system_prompt=system_prompt,
        )
