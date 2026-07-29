"""基于上下文工厂的动态系统提示提供器。"""

from __future__ import annotations

from collections.abc import Callable

from .assembly import CachedSystemPromptAssembler, SystemPromptContext


class ContextualSystemPromptProvider:
    """每次请求重新读取上下文，并复用组装器的最近状态缓存。"""

    def __init__(
        self,
        assembler: CachedSystemPromptAssembler,
        context_factory: Callable[[], SystemPromptContext],
    ) -> None:
        """保存稳定 section 定义和可替换的运行时状态来源。"""

        if not isinstance(assembler, CachedSystemPromptAssembler):
            raise TypeError("assembler 必须是 CachedSystemPromptAssembler 对象。")
        if not callable(context_factory):
            raise TypeError("context_factory 必须是可调用对象。")
        self._assembler = assembler
        self._context_factory = context_factory

    def get_system_prompt(self) -> str | None:
        """用本次真实上下文获取系统提示；不缓存上下文本身。"""

        context = self._context_factory()
        if not isinstance(context, SystemPromptContext):
            raise TypeError("context_factory 必须返回 SystemPromptContext 对象。")
        return self._assembler.get(context)
