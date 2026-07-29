"""S10 系统提示的运行时组装边界。"""

from .assembly import (
    CachedSystemPromptAssembler,
    SystemPromptContext,
    SystemPromptSection,
    SystemPromptSectionRenderer,
)
from .cli import (
    CLI_IDENTITY_SYSTEM_PROMPT,
    CONTEXT_COMPACTION_SYSTEM_PROMPT,
    TASK_DELEGATION_SYSTEM_PROMPT,
    TODO_PLANNING_SYSTEM_PROMPT,
    create_cli_system_prompt_assembler,
    create_cli_system_prompt_context,
)
from .ports import SystemPromptProvider
from .provider import ContextualSystemPromptProvider

__all__ = [
    "CachedSystemPromptAssembler",
    "CLI_IDENTITY_SYSTEM_PROMPT",
    "CONTEXT_COMPACTION_SYSTEM_PROMPT",
    "ContextualSystemPromptProvider",
    "SystemPromptContext",
    "SystemPromptSection",
    "SystemPromptSectionRenderer",
    "SystemPromptProvider",
    "TASK_DELEGATION_SYSTEM_PROMPT",
    "TODO_PLANNING_SYSTEM_PROMPT",
    "create_cli_system_prompt_assembler",
    "create_cli_system_prompt_context",
]
