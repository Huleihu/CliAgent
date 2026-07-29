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

__all__ = [
    "CachedSystemPromptAssembler",
    "CLI_IDENTITY_SYSTEM_PROMPT",
    "CONTEXT_COMPACTION_SYSTEM_PROMPT",
    "SystemPromptContext",
    "SystemPromptSection",
    "SystemPromptSectionRenderer",
    "TASK_DELEGATION_SYSTEM_PROMPT",
    "TODO_PLANNING_SYSTEM_PROMPT",
    "create_cli_system_prompt_assembler",
    "create_cli_system_prompt_context",
]
