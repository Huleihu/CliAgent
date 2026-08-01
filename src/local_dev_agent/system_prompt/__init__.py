"""S10 系统提示的运行时组装边界。"""

from .assembly import (
    CachedSystemPromptAssembler,
    SystemPromptContext,
    SystemPromptSection,
    SystemPromptSectionRenderer,
)
from .cli import (
    BACKGROUND_TASK_SYSTEM_PROMPT,
    CRON_SCHEDULER_SYSTEM_PROMPT,
    CLI_IDENTITY_SYSTEM_PROMPT,
    CONTEXT_COMPACTION_SYSTEM_PROMPT,
    TASK_DELEGATION_SYSTEM_PROMPT,
    TASK_SYSTEM_PROMPT,
    TEAM_SYSTEM_PROMPT,
    TODO_PLANNING_SYSTEM_PROMPT,
    create_cli_system_prompt_assembler,
    create_cli_system_prompt_context,
    create_cli_system_prompt_provider,
)
from .ports import SystemPromptProvider
from .provider import ContextualSystemPromptProvider

__all__ = [
    "BACKGROUND_TASK_SYSTEM_PROMPT",
    "CRON_SCHEDULER_SYSTEM_PROMPT",
    "CachedSystemPromptAssembler",
    "CLI_IDENTITY_SYSTEM_PROMPT",
    "CONTEXT_COMPACTION_SYSTEM_PROMPT",
    "ContextualSystemPromptProvider",
    "SystemPromptContext",
    "SystemPromptSection",
    "SystemPromptSectionRenderer",
    "SystemPromptProvider",
    "TASK_DELEGATION_SYSTEM_PROMPT",
    "TASK_SYSTEM_PROMPT",
    "TEAM_SYSTEM_PROMPT",
    "TODO_PLANNING_SYSTEM_PROMPT",
    "create_cli_system_prompt_assembler",
    "create_cli_system_prompt_context",
    "create_cli_system_prompt_provider",
]
