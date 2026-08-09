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
from .provider import ContextualSystemPromptProvider


CLI_IDENTITY_SYSTEM_PROMPT = """你是本地开发 Agent。

使用已声明的工具完成用户任务，并基于实际执行结果给出结论。"""

TODO_PLANNING_SYSTEM_PROMPT = """处理包含多个步骤的任务时，先创建完整待办清单。

开始事项、完成事项和完成验证后，及时更新待办状态。简单的单步骤任务无需创建待办清单。"""

TASK_SYSTEM_PROMPT = """跨会话或可由不同执行者接手的项目工作，使用持久任务图管理。

创建任务时明确前置依赖；开始实际工作前先认领未被阻塞的任务，完成后再标记完成。任务图记录项目工作与责任归属，待办清单仍用于当前工作中的细粒度执行步骤。"""

TASK_DELEGATION_SYSTEM_PROMPT = """对于需要独立调查、实现或验证的有界复杂子任务，可使用受控委派能力。

委派只返回结构化结论和关联信息；收到结果后由你验收结论，并在需要时自行验证共享工作区中的副作用。简单任务不要委派。"""

BACKGROUND_TASK_SYSTEM_PROMPT = """对于适合异步执行的耗时命令，可显式选择后台运行，并在收到后台任务标识后继续处理不依赖其结果的工作。

后台任务完成通知会在后续模型请求中到达；收到通知后检查状态、退出码和输出摘要，再决定后续动作。短命令以及必须立即读取完整结果的命令应前台执行。"""

CRON_SCHEDULER_SYSTEM_PROMPT = """可以创建、查看或取消五段式 cron 定时任务。

定时任务到期后由独立调度与队列处理线程在 Agent 空闲时启动新的 Run；durable 仅保存任务定义以供下次进程启动恢复，不保证应用关闭期间仍会执行。创建前应确认时间表达式、任务 prompt、是否循环以及是否需要 durable。"""

CONTEXT_COMPACTION_SYSTEM_PROMPT = """当当前历史已冗余或需要切换任务时，可请求 Runtime 在下一轮压缩上下文。

上下文压缩不会修改完整会话历史；不要把它当作文件或消息编辑工具。"""

TEAM_SYSTEM_PROMPT = """需要长期协作而非一次性同步委派时，可创建 Team、登记拥有独立既有 Session 的成员、派发工作并发送成员消息。

持久项目任务图中未认领且依赖已满足的工作，会由空闲成员自主发现和认领；成员完成实际工作并完成任务状态更新后，结果会回传 Lead。临时、任务图之外或必须指定某位成员的工作，仍使用显式 Team 工作分配。消息会持久保存在成员收件箱中，关闭请求优先于自主认领。成员 Runner 仅在本进程运行期间处理消息，应用关闭期间不会自动执行或完成工作。只向已知且属于同一 Team 的成员派活或发消息。"""

WORKTREE_ISOLATION_SYSTEM_PROMPT = """任务图决定“谁做什么”，工作树决定“在哪里做什么”。
Lead 可以为尚未认领的项目任务创建并绑定独立工作树；绑定不会认领任务、设置 owner 或改变任务状态。成员自主认领已绑定任务后，其文件读写和命令执行会在该工作树中进行；未绑定任务仍在主工作区执行。工作树名称必须使用受控的单目录名称。完成后由 Lead 决定保留或删除工作树；删除前应先确认没有未提交改动或未推送提交，只有明确愿意放弃改动时才使用 discard_changes=true。不要假设创建、保留或删除工作树会自动完成、释放或转交任务。"""

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
                "task_system",
                lambda context: TASK_SYSTEM_PROMPT
                if all(
                    context.has_tool(tool_name)
                    for tool_name in (
                        "task_create",
                        "task_list",
                        "task_get",
                        "task_claim",
                        "task_complete",
                    )
                )
                else None,
            ),
            SystemPromptSection(
                "delegation",
                lambda context: TASK_DELEGATION_SYSTEM_PROMPT
                if context.has_tool("task")
                else None,
            ),
            SystemPromptSection(
                "background_tasks",
                lambda context: BACKGROUND_TASK_SYSTEM_PROMPT
                if context.has_tool("bash")
                else None,
            ),
            SystemPromptSection(
                "cron_scheduler",
                lambda context: CRON_SCHEDULER_SYSTEM_PROMPT
                if all(
                    context.has_tool(tool_name)
                    for tool_name in ("schedule_cron", "list_crons", "cancel_cron")
                )
                else None,
            ),
            SystemPromptSection(
                "context_compaction",
                lambda context: CONTEXT_COMPACTION_SYSTEM_PROMPT
                if context.has_tool("compact")
                else None,
            ),
            SystemPromptSection(
                "teams",
                lambda context: TEAM_SYSTEM_PROMPT
                if all(
                    context.has_tool(tool_name)
                    for tool_name in (
                        "create_team",
                        "add_teammate",
                        "assign_team_work",
                        "send_team_message",
                    )
                )
                else None,
            ),
            SystemPromptSection(
                "worktree_isolation",
                lambda context: WORKTREE_ISOLATION_SYSTEM_PROMPT
                if all(
                    context.has_tool(tool_name)
                    for tool_name in (
                        "create_worktree",
                        "keep_worktree",
                        "remove_worktree",
                    )
                )
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


def create_cli_system_prompt_provider(
    *,
    workspace: Path,
    registry: ToolRegistry,
    skill_catalog: SkillCatalog,
) -> ContextualSystemPromptProvider:
    """创建父 Agent 的动态提示提供器，技能目录保持本次启动快照。"""

    assembler = create_cli_system_prompt_assembler(skill_catalog)
    return ContextualSystemPromptProvider(
        assembler,
        lambda: create_cli_system_prompt_context(
            workspace=workspace,
            registry=registry,
        ),
    )
