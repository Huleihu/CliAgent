"""CLI 父 Agent 的系统提示 section 与真实状态适配。"""

from __future__ import annotations

from pathlib import Path

from local_dev_agent.skills import SkillCatalog, format_skill_catalog
from local_dev_agent.tools import ToolRegistry

from .assembly import (
    CachedSystemPromptAssembler,
    SystemPromptContext,
    SystemPromptSection,
)


CLI_IDENTITY_SYSTEM_PROMPT = """你是本地开发 Agent。

使用已声明的工具完成用户任务，并基于实际执行结果给出结论。"""

TODO_PLANNING_SYSTEM_PROMPT = """处理包含多个步骤的任务时，先创建完整待办清单。

开始事项、完成事项和完成验证后，及时更新待办状态。简单的单步骤任务无需创建待办清单。"""

TASK_DELEGATION_SYSTEM_PROMPT = """对于需要独立调查、实现或验证的有界复杂子任务，可使用受控委派能力。

委派只返回结构化结论和关联信息；收到结果后由你验收结论，并在需要时自行验证共享工作区中的副作用。简单任务不要委派。"""

CONTEXT_COMPACTION_SYSTEM_PROMPT = """当当前历史已冗余或需要切换任务时，可请求 Runtime 在下一轮压缩上下文。

上下文压缩不会修改完整会话历史；不要把它当作文件或消息编辑工具。"""

_CLI_SKILL_CATALOG_INSTRUCTION = "需要某项技能的完整说明时，使用已声明的技能加载工具。"


def create_cli_system_prompt_context(
    *,
    workspace: Path,
    registry: ToolRegistry,
) -> SystemPromptContext:
    """从 CLI 真实工作区和当前工具目录生成提示选择上下文。"""

    if not isinstance(workspace, Path):
        raise TypeError("workspace 必须是 Path 对象。")
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry 必须是 ToolRegistry 对象。")
    return SystemPromptContext.create(
        workspace=str(workspace.resolve()),
        enabled_tool_names=(definition.name for definition in registry.list_definitions()),
    )


def create_cli_system_prompt_assembler(
    skill_catalog: SkillCatalog,
) -> CachedSystemPromptAssembler:
    """创建父 Agent 的 section 组装器，不重复声明 Anthropic 工具 schema。"""

    if not isinstance(skill_catalog, SkillCatalog):
        raise TypeError("skill_catalog 必须是 SkillCatalog 对象。")
    skill_catalog_prompt = format_skill_catalog(
        skill_catalog,
        instruction=_CLI_SKILL_CATALOG_INSTRUCTION,
    )
    return CachedSystemPromptAssembler(
        (
            SystemPromptSection("identity", lambda _: CLI_IDENTITY_SYSTEM_PROMPT),
            SystemPromptSection(
                "workspace",
                lambda context: f"当前工作区：{context.workspace}",
            ),
            SystemPromptSection(
                "todo",
                lambda context: TODO_PLANNING_SYSTEM_PROMPT
                if context.has_tool("todo_write")
                else None,
            ),
            SystemPromptSection(
                "delegation",
                lambda context: TASK_DELEGATION_SYSTEM_PROMPT
                if context.has_tool("task")
                else None,
            ),
            SystemPromptSection(
                "context_compaction",
                lambda context: CONTEXT_COMPACTION_SYSTEM_PROMPT
                if context.has_tool("compact")
                else None,
            ),
            SystemPromptSection(
                "skills",
                lambda context: skill_catalog_prompt
                if context.has_tool("load_skill")
                else None,
            ),
        )
    )
