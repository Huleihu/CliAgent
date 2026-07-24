# 项目交接

## 当前状态

- 已完成 Phase 1 的第二十个教学式迭代：状态机、JSON 文件状态仓储、最小内部事件协议、Runtime 输入编排、内容块模型协议、有界 Agent Loop、统一 logging、受控工具框架、DeepSeek 真实模型适配、多轮工具调用闭环、最小交互式启动入口、真实只读文件工具、跨 Run 会话历史与统一参数校验。
- 已完成 S4 的第 1 个教学式小步：定义了独立 Hook 包的事件、不可变上下文和结构化控制结果契约；尚未注册或触发 Hook，因此现有 Runtime 与工具执行行为保持不变。
- 已完成 S4 的第 2 个教学式小步：实现 Hook 注册与触发基础设施；注册顺序稳定，首个阻止结果会终止该事件的后续回调，但尚未接入 Runtime 或工具执行。
- 已完成 S4 的第 3 个教学式小步：`PreToolUse` 已接入工具执行边界；工具仅在查找和参数校验通过后触发 Hook，被阻止时不运行工具实现并将结构化失败结果回填模型。
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
- 实现 `UserInputRuntimeService`：消费已关联既有 Session 的 `UserInputEvent`，创建排队中的 `RunState` 与待执行的规划 `StepState`，再将 Run、Step、激活后的 Session 依次保存到 JSON 仓储。
- 新增最小 Runtime 编排单元测试，覆盖状态创建与持久化、缺失 Session 的中文错误，以及活跃 Run 存在时拒绝并发用户输入。
- 定义可替换的 `ModelClient`、`ModelRequest` 与 `ModelResponse` 端口，并实现不访问外部服务的确定性 `FakeModel`。
- 实现 `MinimalAgentLoop` 纯文本完成路径：Run 依次经过恢复、运行和完成；规划 Step 依次经过执行和成功；完成后释放 Session 的活跃 Run，所有状态变更均保存到 JSON 仓储。
- 添加 Fake Model 与最小 Agent Loop 单元测试，覆盖模型请求与固定响应、完整状态迁移、JSON 持久化和会话释放。
- 新增基于标准库 `logging` 的统一日志配置：控制台输出可读日志，`var/logs/agent.jsonl` 输出带滚动策略的结构化 JSONL 日志，并保留事件、会话、运行和步骤关联标识。
- Runtime 输入编排与最小 Agent Loop 已记录关键生命周期 INFO 日志；模型调用异常会记录带异常栈的 ERROR 日志后继续抛出，由后续错误恢复策略处理。
- 添加 logging 单元测试，覆盖控制台与文件 Handler、JSONL 关联字段、重复配置去重，以及 Runtime/Agent Loop 关键日志事件。
- 将内部 `ModelResponse` 升级为与 Provider 解耦的内容块协议：包含 `stop_reason`、多个 `TextBlock` / `ToolUseBlock`，并提供文本完成的便捷构造方法；`ToolUseBlock` 保留调用标识、工具名称与冻结后的顶层参数映射。
- `FakeModel` 改为返回预设的规范化 `ModelResponse`；`MinimalAgentLoop` 仅在 `end_turn` 且含文本块时完成 Run，收到 `tool_use` 等未实现分支时记录 WARNING 并拒绝将 Run/Step 标记为成功。
- 添加内容块模型协议与工具调用安全分支测试，覆盖多文本块、工具调用结构、工具参数顶层不可变、非法停止原因组合，以及未执行工具调用不得完成 Run。
- 新增 `local_dev_agent.tools` 工具框架：以稳定 `Tool` 端口隔离工具实现；`ToolDefinition`、`ToolCallRequest`、`ToolCallResult` 提供不可变、JSON 原生值约束的调用契约，并保留 `call_id` 以对接后续 `ToolUseBlock.tool_use_id`。
- 实现 `ToolRegistry`、`FunctionTool`、`FakeTool` 与 `ToolExecutor`：执行器统一处理工具查找、必填参数校验、异常收束和耗时统计，将预期失败转换为结构化 `ToolCallResult`，不让工具异常直接进入 Agent Loop。
- 实现受控 `ToolDiscovery`：仅扫描代码显式指定 Python 包的直接子模块，发现公开的 `Tool` 实例或 `create_tool` 工厂；拒绝任意路径扫描、递归扫描、重复工具名、无效工厂和导入失败。
- 添加工具框架单元测试，覆盖成功执行与调用标识透传、缺失参数、未知工具、工具异常、非法返回值、注册去重、顶层参数冻结，以及实例/工厂动态发现和发现失败。
- 新增 `DeepSeekSettings` 与 `DeepSeekAnthropicModelClient`：从 `.env` 中的 `DEEPSEEK_API_KEY`、`DEEPSEEK_ANTHROPIC_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_MAX_TOKENS` 读取显式配置，使用已有 `anthropic` SDK 访问 DeepSeek Anthropic 兼容接口。
- DeepSeek Provider 将 Anthropic 格式的 `text`、`tool_use` 内容块和停止原因映射到既有 `ModelResponse` 协议；暂不向真实模型声明工具，因此工具调用执行与结果回填仍保持为后续独立步骤。
- 更新 `.env.example` 与 `README.md`，说明 DeepSeek 本地配置和模型客户端创建方式；真实 `.env` 未被读取、修改或提交。
- 添加 DeepSeek Provider 单元测试，覆盖环境配置读取与校验、文本/工具调用响应映射、SDK 请求参数、Provider 异常和未知停止原因；全部使用注入的假 SDK 客户端，不访问网络、不产生 API 费用。
- 开始按 `learnClaude/s01_agent_loop` 的核心循环分步实现：新增不可变 `ModelMessage`、`MessageRole`、`ToolResultBlock` 与支持完整消息历史的 `ModelRequest`；用户消息、助手工具调用和工具结果的角色/内容组合均在协议层校验。
- 保留 `ModelRequest(user_input=...)` 旧接口，并通过 `conversation` 属性规范化为首条用户消息，避免现有纯文本 Runtime、Fake Model 与 DeepSeek Provider 行为变化。
- 添加多轮对话协议单元测试，覆盖旧接口兼容、多轮工具对话顺序、工具结果快照冻结、角色内容校验及上下文来源互斥。
- 继续改进版 `learnClaude/s01_agent_loop` 的第 2 小步：DeepSeek Provider 现可将 `ModelRequest.conversation` 转换为 Anthropic 兼容的多轮 `messages`，并将 `ToolResultBlock` 转换为带调用关联和错误标识的 `tool_result` 内容块；旧单文本请求继续保持原始请求形态。
- 添加 DeepSeek 多轮请求序列化测试，覆盖用户文本、助手 `tool_use`、用户 `tool_result` 的顺序、字段和结构化 JSON 结果编码；本步不向模型声明工具，也不执行工具或修改 Agent Loop。
- 继续改进版 `learnClaude/s01_agent_loop` 的第 3 小步：`ModelRequest` 现可携带现有 `ToolDefinition` 元组，DeepSeek Provider 仅在工具非空时将其转换为 Anthropic `tools` 声明；模型侧与执行侧复用同一份工具 schema，避免声明漂移。
- 添加模型工具声明测试，覆盖请求保留工具定义与 DeepSeek `name`、`description`、`input_schema` 映射；本步仍不执行工具、不改变 Agent Loop。
- 完成改进版 `learnClaude/s01_agent_loop` 的第 4 小步：`MinimalAgentLoop` 现按内容块检测 `ToolUseBlock`，从 `ToolRegistry` 导出工具定义，经 `ToolExecutor` 串行执行调用，追加 `ToolResultBlock` 后继续请求模型，直到收到最终文本。
- 有界 Loop 默认最多进行 10 次模型调用；达到上限时将 Run 转为 `exhausted`、释放 Session 活跃 Run 并抛出中文错误，避免模型持续请求工具导致无限循环。
- 每轮模型决策与每次工具执行均持久化 Step：首个既有 `PLAN` Step 表示首次模型决策，工具调用创建 `TOOL` Step，工具回填后的模型调用创建 `MODEL` Step。工具失败会形成 `is_error=True` 的结果块回填给模型，而非中断整个 Loop。
- 添加 Agent Loop 单元测试，覆盖纯文本完成、工具执行与结果回填、多轮工具声明、工具失败回填和最大轮次耗尽；全部使用 Fake Model/Fake Tool，不访问真实 API。
- 新增 `local_dev_agent.main` 与 `python -m local_dev_agent` 启动方式：启动时加载 `.env`、配置日志、创建 JSON 状态仓储与 DeepSeek Provider，并在终端循环中执行“用户输入 → UserInputRuntimeService.handle() → MinimalAgentLoop.execute() → 打印最终文本”。
- 启动入口为同一进程复用一个 Session、每条输入创建一个独立 Run 的最小 s01 Demo；当前尚未跨 Run 保存或复用消息历史，也尚未注册真实工具，二者留给后续小步。
- 添加启动入口连接测试，覆盖从终端输入编排函数到 Runtime 输入服务和 Agent Loop 的完整无网络连接。
- 更新 README，说明 `python -m local_dev_agent` 的启动方式、退出命令和本地状态/日志目录。
- 新增 `WorkspaceBoundary` 与 `ListFilesTool`：仅列出工作区内符合 glob 模式的文件，统一拒绝绝对路径、上级目录和解析后越界的目录；工具不读取内容、不写入文件，也不执行命令。
- `list_files` 返回稳定排序的工作区相对路径，并通过默认 200、最大 1000 条的结果上限与 `truncated` 标记控制模型上下文大小。
- 最小 CLI 启动入口现默认注册 `list_files`，真实 Provider 可在工具声明、执行和结果回填之间形成首个只读闭环。
- 添加 `list_files` 单元测试与真实工具驱动的 Agent Loop 闭环测试，覆盖模式筛选、稳定排序、结果截断、工作区越界拒绝、CLI 注册和结果回填。
- 修复 DeepSeek 工具结果回填后的 thinking 兼容性：Provider 现在显式关闭 thinking 模式，避免当前不持久化推理内容的内部协议在后续请求中丢失必要内容，导致模型仅返回思考块或空内容。
- Provider 对意外的仅思考或空响应会报告内容类型摘要，不记录思考正文；补充请求参数和仅思考响应的单元测试。
- 新增 `ReadFileTool`：复用 `WorkspaceBoundary` 的文件解析规则，只读取工作区内普通 UTF-8 文本文件；支持从指定行开始读取，并限制最多 1000 行和 20000 个字符，超出时以 `truncated` 标记返回。
- 最小 CLI 默认注册 `read_file`；添加读取行范围、字符截断、越界、目录、非 UTF-8 文件、非法行参数与真实工具回填闭环测试。
- 最小 CLI 的默认工作区从终端当前目录改为项目根目录下的 `sandbox/`；因此从任意目录启动时，文件工具边界和本地状态/日志位置保持一致。
- 将本地 `sandbox/` 工作区加入 Git 忽略规则，避免其运行状态、日志和临时测试文件进入版本控制。
- 新增独立 `ConversationRepository` 与 `JsonFileConversationRepository`：以按 Session 分文件的版本化 JSON Transcript 持久化用户消息、助手响应、工具调用和工具结果；不将消息塞入既有 Session/Run/Step 状态快照。
- `MinimalAgentLoop` 在每个消息边界追加 Transcript，并在新的 Run 开始时加载同一 Session 的完整历史；最小 CLI 已完成装配。
- 添加消息 Transcript 的跨实例恢复、损坏文件、缺失历史，以及跨 Run 复用已发现文件并直接调用 `read_file` 的闭环测试。
- 新增 `argument_validator`：`ToolExecutor` 现在在 Handler 前统一校验现有工具 Schema 所需的对象、字符串、整数、布尔值、数组、嵌套对象、必填字段与未知字段；无效调用会回填结构化错误且不会进入工具实现。
- 添加嵌套 JSON Schema 校验测试，覆盖正确调用、错误类型、未知字段、数组元素错误和嵌套必填字段遗漏。
- 新增 `local_dev_agent.hooks` 契约包：`HookEvent` 覆盖用户输入、工具执行前后与停止四个生命周期事件；四类事件使用各自的冻结上下文，复用既有 `ToolCallRequest`、`ToolCallResult` 和 `ModelResponse`，不复制或放宽现有协议。
- 新增 `HookResult` 与 `HookDecision`：当前明确区分 `continue` 和带中文原因的 `block`，为下一步注册表和未来 S3 的 `PreToolUse` 权限适配保留稳定边界。
- 添加 Hook 契约单元测试，覆盖事件值、上下文关联与不可变性、非法关联标识、协议对象类型和控制结果组合。
- 新增 `Hook` 端口、`HookRegistry` 与 `HookRunner`：注册表按生命周期事件隔离 Hook，保持注册顺序并拒绝同事件重名；运行器按顺序触发，首个 `block` 会阻止后续回调，回调异常和非法返回值收束为中文 `HookExecutionError`。
- Hook 上下文通过类级事件标识自描述所属生命周期，运行器拒绝事件与上下文不匹配的调用；添加注册表、触发顺序、阻止短路、上下文错配和回调失败单元测试。
- `ToolExecutor` 现可选注入 `HookRunner`：已启用时必须提供与当前请求一致的 `PreToolUseContext`，防止调用方绕过未来的安全 Hook；参数校验失败和未知工具仍在 Hook 之前直接返回结构化失败结果。
- 新增 `ToolHookBlockedError`：执行前 Hook 返回 `block` 时，工具实现不会运行，失败结果保留原始 `call_id` 并正常回填模型；`MinimalAgentLoop` 会构造携带 Session、Run、Tool Step 关联标识的执行前上下文。
- Hook 契约对模型与工具协议改为仅类型检查时导入、运行时在校验点延迟导入，消除 `Hook → 工具协议 → ToolExecutor → Hook` 的导入环，同时不改变契约类型校验。
- 添加执行前 Hook 集成测试，覆盖校验先于 Hook、阻止后零工具调用、缺失或错配上下文拒绝执行，以及 Agent Loop 向模型回填 Hook 阻止结果与完整关联标识。

## 验证

- `anthropic`、`python-dotenv`、`pytest` 可在 Conda 环境中导入。
- `ruff` 可运行。
- 已人工核对 `TDD.md` 与 `AGENT_REQUIREMENTS_CHECKLIST.txt` 的 S01–S30 覆盖关系；本次仅修改文档，未运行代码测试。
- `python -m pytest`：124 passed（覆盖状态机、JSON 文件状态仓储、会话 Transcript、最小内部事件协议、Runtime 输入编排、内容块模型协议、有界 Agent Loop、统一 logging、受控工具框架、DeepSeek Provider、多轮工具调用闭环、最小交互式启动入口、只读文件工具与 Hook 契约、注册、触发和执行前阻止）。
- `python -m ruff check src tests`：通过。

## 下一步

- 进入 S4 的第 4 个教学式小步：将 `PostToolUse` 接入 `ToolExecutor`。工具执行已收束为 `ToolCallResult` 后触发 Hook，向 Hook 提供冻结的请求和结果；初版仅允许观察与审计，不允许改写已产生的工具结果。随后再接入用户输入和停止事件，并在 S3 中将权限策略接入 `PreToolUse`。
