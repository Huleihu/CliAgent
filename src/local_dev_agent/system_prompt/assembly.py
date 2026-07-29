"""运行时系统提示的分段组装与确定性缓存。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SystemPromptContext:
    """描述影响系统提示 section 选择的最小运行时状态。"""

    workspace: str
    enabled_tool_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """冻结并规范化工具集合，使等价状态命中同一缓存项。"""

        if not isinstance(self.workspace, str) or not self.workspace.strip():
            raise ValueError("字段“workspace”必须是非空字符串。")
        if not isinstance(self.enabled_tool_names, tuple):
            raise ValueError("字段“enabled_tool_names”必须是字符串元组。")
        if not all(isinstance(name, str) and name.strip() for name in self.enabled_tool_names):
            raise ValueError("字段“enabled_tool_names”必须是非空字符串元组。")
        normalized_tool_names = tuple(sorted(name.strip() for name in self.enabled_tool_names))
        if len(set(normalized_tool_names)) != len(normalized_tool_names):
            raise ValueError("字段“enabled_tool_names”不能包含重复工具名称。")
        object.__setattr__(self, "enabled_tool_names", normalized_tool_names)

    @classmethod
    def create(
        cls,
        *,
        workspace: str,
        enabled_tool_names: Iterable[str] = (),
    ) -> "SystemPromptContext":
        """创建上下文并复制调用方的可变工具集合。"""

        return cls(
            workspace=workspace,
            enabled_tool_names=tuple(enabled_tool_names),
        )

    def has_tool(self, tool_name: str) -> bool:
        """判断某个工具是否真实注册；名称不进入提示正文。"""

        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("字段“tool_name”必须是非空字符串。")
        return tool_name.strip() in self.enabled_tool_names

    def to_cache_key(self) -> str:
        """生成跨等价上下文稳定的 JSON 缓存键。"""

        return json.dumps(
            {
                "enabled_tool_names": self.enabled_tool_names,
                "workspace": self.workspace,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


SystemPromptSectionRenderer = Callable[[SystemPromptContext], str | None]


@dataclass(frozen=True, slots=True)
class SystemPromptSection:
    """一个具名的系统提示片段，可按运行时上下文选择性加载。"""

    name: str
    renderer: SystemPromptSectionRenderer = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """拒绝无法诊断的匿名或不可调用 section 定义。"""

        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("字段“name”必须是非空字符串。")
        if not callable(self.renderer):
            raise ValueError("字段“renderer”必须是可调用对象。")

    def render(self, context: SystemPromptContext) -> str | None:
        """渲染 section；返回 None 表示当前状态不加载该片段。"""

        if not isinstance(context, SystemPromptContext):
            raise TypeError("context 必须是 SystemPromptContext 对象。")
        content = self.renderer(context)
        if content is None:
            return None
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"系统提示 section“{self.name}”必须返回非空字符串或 None。")
        return content.strip()


class CachedSystemPromptAssembler:
    """按注册顺序组装系统提示，并缓存最近一次等价运行时状态。"""

    def __init__(self, sections: Iterable[SystemPromptSection]) -> None:
        """复制 section 快照，避免调用方后续改动组装顺序。"""

        self._sections = tuple(sections)
        if not all(isinstance(section, SystemPromptSection) for section in self._sections):
            raise ValueError("sections 必须只包含 SystemPromptSection 对象。")
        names = tuple(section.name for section in self._sections)
        if len(set(names)) != len(names):
            raise ValueError("系统提示 section 名称不能重复。")
        self._last_context_key: str | None = None
        self._last_prompt: str | None = None

    def get(self, context: SystemPromptContext) -> str | None:
        """返回当前上下文的提示；未变化时避免重复执行 section 渲染。"""

        if not isinstance(context, SystemPromptContext):
            raise TypeError("context 必须是 SystemPromptContext 对象。")
        context_key = context.to_cache_key()
        if context_key == self._last_context_key:
            return self._last_prompt
        prompt_parts = tuple(
            content
            for section in self._sections
            if (content := section.render(context)) is not None
        )
        prompt = "\n\n".join(prompt_parts) if prompt_parts else None
        self._last_context_key = context_key
        self._last_prompt = prompt
        return prompt
