# 项目交接

## 当前状态

- 已完成 Phase 1 的第五个教学式迭代：状态机、JSON 文件状态仓储与最小内部事件协议。
- 使用 Conda 环境 `local-dev-agent`（Python 3.13）。

## 已完成

- 初始化 Git 仓库与 `.gitignore`。
- 添加 `requirements.txt` 并安装运行、测试和静态检查依赖。
- 配置 VS Code 使用 `local-dev-agent` 解释器（本地 `.vscode/settings.json`）。
- 添加项目开发规则：`AGENTS.md`。
- 约定提交信息使用 Conventional Commits 标题与项目符号正文。
- 已配置本仓库 Git 身份，并完成首次提交 `chore: 初始化项目开发环境`；提交标题与正文使用中文。
- 添加 `environment.yml`、`.env.example` 与根目录 `README.md`，完善环境复现和项目上手说明。
- 已提交环境复现与上手文档更新：`docs: 完善项目上手配置`。
- 新增 `TDD.md`，完成本地 CLI Agent Runtime 的企业级目标架构设计，覆盖分层架构、核心运行流程、四级状态、工具与权限、Context/Memory、Multi Agent、MCP、持久化、可观测性、目录结构和四阶段路线。
- TDD 明确首版默认技术决策：Anthropic 首个 Provider、PowerShell 首个 Shell 适配器、SQLite + 本地工件 + JSONL/滚动日志，并通过端口与适配器保留替换能力。
- 新增 `pyproject.toml`、`src/local_dev_agent/` 与 `tests/` 的最小 Python 包布局。
- 实现不可变 `RunState`、`RunStatus`、`RunTransition` 和集中式合法状态迁移校验；每次状态迁移生成新版本与历史记录，避免调用方静默修改待持久化状态。
- 添加 Run 状态机单元测试，覆盖正常完成、审批暂停恢复、非法跳转、终态保护和不可变性。
- 更新 `AGENTS.md`：代码注释、文档字符串及面向人的异常/日志文本统一使用中文；本次新增状态机模块的文档字符串和异常消息已同步中文化。
- 完整复查状态机源码后，补齐遗漏的时间戳异常消息，并将说明文字中的英文运行时术语统一改为中文；英文仅保留为代码标识符与协议枚举值。
- 实现 `StepState`、`StepStatus`、`StepType` 与独立步骤迁移历史，覆盖模型、工具、验证、反思和委派等动作类型。
- 新增共享时间规范化模块，统一 Run 与 Step 的 UTC 转换和无时区时间拒绝规则；`RunState` 的外部行为保持不变。
- 添加 Step 状态机单元测试，覆盖成功、等待恢复、不确定结果协调、非法跳转、终态保护、不可变性、中文错误信息与尝试次数校验。
- 更新 `AGENTS.md`：每个已验证且边界清晰的教学式小步完成后，主动提醒用户可以提交并提供建议提交信息；未经用户明确要求不自动提交。
- 实现 `SessionState`、`SessionStatus` 与会话生命周期迁移历史，覆盖 `created → active ↔ suspended → archived`，以及等待人工处理的 `corrupted`、`needs_migration` 终态。
- 建立 `Session → Run → Step` 的状态关联边界：Session 仅保存 `active_run_id`，Run 继续通过 `session_id` 归属会话，Step 继续通过 `run_id` 归属运行；完整 Run 历史留给后续 Repository 查询，避免重复快照状态。
- 添加会话状态机单元测试，覆盖会话生命周期、顺序关联多个 Run、活跃 Run 排他性、活跃 Run 与会话迁移互斥、非法跳转、终态保护、不可变性与中文时间校验。
- 定义 `StateRepository` 存储端口，并实现 `JsonFileStateRepository`：Session、Run、Step 分别写入 `var/state/sessions/`、`var/state/runs/`、`var/state/steps/` 下的可读 JSON 文件。
- 新增带 `schema_version` 的 JSON 编解码模块，完整保存状态转换历史与 UTC 时间戳；JSON 文件采用临时文件加原子替换写入，避免中断后留下半截快照。
- JSON 仓储按 `state_version` 执行乐观锁校验，拒绝旧快照覆盖新版本；支持按 `session_id` 查询 Run、按 `run_id` 查询 Step，并将 `var/` 加入 Git 忽略规则。
- 添加 JSON 状态仓储单元测试，覆盖跨 Repository 实例恢复、层级查询、版本冲突、可读文件结构、缺失状态、损坏文件中文错误与转换历史恢复。
- 将 pytest 临时目录固定为工作区内且已忽略的 `.pytest-tmp/`，避免测试依赖系统临时目录权限。
- 新增不可变、版本化的 `UserInputEvent` 与 `EventType`，用于表示已接收、等待 Runtime 处理的用户输入；事件带 `event_id`、`session_id`、UTC 时间戳与内容，但暂不承担创建 Run 或调用模型的职责。
- 添加用户输入事件单元测试，覆盖协议字段、自动 ID、UTC 规范化、无时区时间、空输入中文错误与不可变性。
- 更新 `.gitignore`：忽略 pytest 异常临时缓存目录，减少本地文件树噪音。

## 验证

- `anthropic`、`python-dotenv`、`pytest` 可在 Conda 环境中导入。
- `ruff` 可运行。
- 已人工核对 `TDD.md` 与 `AGENT_REQUIREMENTS_CHECKLIST.txt` 的 S01–S30 覆盖关系；本次仅修改文档，未运行代码测试。
- `python -m pytest`：36 passed（覆盖状态机、JSON 文件状态仓储与最小内部事件协议）。
- `python -m ruff check src tests`：通过。

## 下一步

- 检查通过后，继续 Phase 1 的下一个小步：实现最小 Runtime 编排服务，消费 `UserInputEvent`，创建并持久化 Session、Run 与首个 Step。
