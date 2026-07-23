# Local Dev Agent Runtime 技术设计文档（TDD）

> 状态：Draft v1.0
> 适用范围：本地 CLI Agent Runtime；覆盖需求 S01–S30 的目标架构与分阶段落地方案
> 当前技术基线：Python 3.13、Anthropic SDK、本地 Windows/PowerShell
> 设计原则：模型负责理解、选择与推理；Harness 负责能力边界、状态、权限、上下文、隔离、恢复与治理

## 0. 文档约定与关键决策

本文描述目标架构，不代表所有模块在首个版本中同时实现。架构采用“端口与适配器”思想：核心 Runtime 只依赖稳定协议，不直接依赖模型 SDK、SQLite、Shell、MCP 或终端 UI。这样可以按阶段替换基础设施，而不重写 Agent Loop。

首版采用以下默认决策：

| 主题 | 决策 | 原因 |
|---|---|---|
| 产品界面 | Phase 1–3 仅提供 CLI，Phase 4 增加 API/Worker | 先验证 Harness，不让 Web/分布式复杂度干扰核心循环 |
| 模型 | Phase 1 接入 Anthropic，但定义通用 Model Port | 复用现有依赖，同时避免业务层绑定单一 Provider |
| Shell | Phase 1 实现 PowerShell 适配器，后续可新增 Bash | 符合当前运行环境；命令语义差异由适配器隔离 |
| 本地存储 | SQLite 保存事务状态；工件目录保存大对象；JSONL/滚动文件保存日志 | 单机可靠、便于检查和备份，也保留迁移到服务端存储的边界 |
| 状态模型 | Snapshot + append-only Event/Trace 的混合方式 | Snapshot 恢复快，事件链便于审计、重放和 Eval |
| 执行模型 | 单 Agent 单 Run 串行提交状态；工具可受控并发 | 避免对话顺序和 checkpoint 竞态；并发能力在明确边界内开放 |
| 安全默认值 | 最小权限、工作区边界、默认拒绝未知高风险动作 | 本地 Agent 能触达文件与命令，安全边界必须先于能力扩展 |

所有持久化记录使用带版本的结构化协议。内部对象不跨模块直接暴露 ORM 实体；模块间通过 DTO、事件或 Port 交互。

---

# 1. 项目目标

## 1.1 系统定位

Local Dev Agent Runtime 是一个本地运行的 CLI Agent Harness。它不是聊天界面，也不是把单次模型调用包装成命令，而是承载长任务、工具调用、权限审批、上下文控制、故障恢复和可观测性的运行时。

系统面向两个目标：

1. **学习目标**：通过真实工程边界理解企业级 Agent Harness 的核心机制，而不是只学习 Prompt 或简单 ReAct 循环。
2. **产品目标**：形成可演进的本地 Runtime 内核，未来可以扩展到多模型、多 Agent、MCP、Eval 和服务化，而不推翻早期实现。

## 1.2 解决的问题

- 模型输出不能直接等同于可信动作，需要 Schema 校验、权限判断、执行隔离和结果回填。
- 长对话会超过 Token 窗口，需要预算、裁剪、压缩、检索和可追溯的 Prompt 快照。
- CLI 或进程可能随时退出，需要从持久化状态恢复，而不是依赖内存中的 messages。
- 开发任务常跨多个步骤、工具和人工审批，需要显式的 Plan、Run、Step 和 Checkpoint。
- 新工具、新模型和外部 MCP Server 不应要求修改核心循环。
- 多 Agent 会引入上下文泄漏、消息竞态、任务重复认领和文件冲突，需要独立状态与明确协议。
- 企业场景要求能解释“发生了什么、为什么允许、失败在哪里、成本多少、能否重放”。

## 1.3 参考思想

本项目参考 Claude Code、Codex 等现代编码 Agent 的共性思想，但不复制其内部实现：

- **Agentic loop**：模型调用与工具结果回填形成闭环，模型根据真实观察继续决策。
- **Harness/Model 分工**：模型做非确定性推理；Runtime 做确定性的权限、状态、资源和恢复控制。
- **工具是受控能力**：工具以结构化 Schema 暴露，实际执行统一经过策略管线。
- **最小上下文与渐进披露**：只在需要时注入技能、记忆和文件内容，避免知识全部常驻。
- **Plan/Execute/Verify 分离**：计划和验证是一等运行阶段，而非只存在于隐藏 Prompt 中。
- **Human-in-the-loop**：高风险动作在执行前暂停，并能跨进程恢复等待状态。
- **隔离协作**：Subagent 使用独立上下文，团队通过任务与消息协议协作。
- **可恢复、可审计**：每次运行有稳定 ID、事件链、checkpoint 和可重放输入快照。

## 1.4 非目标

- 不复刻任一商业产品的 UI、私有 Prompt 或内部协议。
- Phase 1 不实现完整 IDE、Web UI、分布式调度、向量数据库或所有模型 Provider。
- 不保证任意模型输出都能完成任务；Runtime 保证的是执行边界、状态一致性与可诊断性。
- 不把模型的“思维过程”作为可观测性目标；只记录可合法保存的输入、输出、决策摘要、动作和结果。

## 1.5 质量属性

| 属性 | 目标 |
|---|---|
| 安全性 | 未知高风险动作默认拒绝；所有工具先校验、后授权、再执行 |
| 可恢复性 | 每个外部副作用前后有持久化边界；进程重启后可识别未决动作 |
| 可扩展性 | 新增 Tool/Provider/Storage Adapter 不修改 Agent Loop |
| 可观测性 | Run、Model Call、Tool Call、Approval 可用统一 ID 关联 |
| 可测试性 | 核心决策依赖接口；支持 fake model、fake tool、临时数据库与确定性时钟 |
| 可迁移性 | CLI、本地 SQLite 和本地工件只是适配器，不进入领域模型 |
| 向后兼容 | Schema、Prompt、Tool 和 Checkpoint 均带版本；升级需有迁移策略 |

---

# 2. 整体架构设计

## 2.1 架构风格

系统采用分层架构与 Ports/Adapters 组合。Runtime 是应用编排核心；领域对象和协议位于内层；CLI、模型 SDK、Shell、SQLite、MCP 等位于外层。依赖方向始终指向抽象。

```text
User / Runtime Event
        |
        v
+----------------------- CLI Layer -----------------------+
        |
        v
+------------------ Agent Runtime Layer ------------------+
  |         |          |          |             |
  v         v          v          v             v
Model     Tool      Context     Memory      Observability
Layer     Layer      Layer       Layer          Layer
  |         |          |          |             |
  +---------+----------+----------+-------------+
                         |
                         v
                  Storage Layer

外部适配器：Model Provider SDK / OS & Shell / MCP Server /
           SQLite / Artifact Store / Console & File Sink
```

## 2.2 分层职责

### 2.2.1 CLI Layer

职责：

- 解析 `start`、`resume`、`run`、`approve`、`deny`、`session list`、`trace show` 等命令。
- 将终端输入转为结构化 `UserInputEvent` 或 `HumanDecisionEvent`。
- 渲染流式文本、计划、工具状态、审批请求和最终结果。
- 处理 Ctrl+C、退出码、非交互模式和日志级别，但不决定业务状态。

为什么单独分层：终端交互会持续变化，未来还会出现 API 或 Worker 入口。CLI 只调用 `RuntimeFacade`，不能直接操作数据库、Provider SDK 或 Tool Handler。

### 2.2.2 Agent Runtime Layer

职责：

- 运行 Input → Recovery → Context → Plan → Execute → Observe → Reflect → Persist 状态机。
- 管理 Session、Run、Step、Checkpoint 的生命周期与状态转换。
- 协调 Model、Tool、Context、Memory、Task、Approval 和 Event Bus。
- 应用取消、重试、超时、最大步数、成本上限等运行策略。
- 产生领域事件并确定 checkpoint 边界。

为什么是核心：它表达 Harness 的稳定业务流程，但不关心 Anthropic 消息格式、SQLite SQL 或 PowerShell 实现。

### 2.2.3 Model Layer

职责：

- 定义统一 `ModelClient`、`ModelRequest`、`ModelResponse`、流式事件和 Usage。
- 将内部消息、工具 Schema、结构化输出要求转换为 Provider 格式。
- 实现 Provider 级超时、限流重试、错误归一化、模型路由与 fallback。
- 保存可重放的模型配置和 Prompt Snapshot 引用。

为什么需要抽象：不同 Provider 的工具调用、缓存、Token 统计和错误类型不同。归一化发生在适配器内，Runtime 只理解内部协议。

### 2.2.4 Tool Layer

职责：

- 管理 Tool Schema、版本、来源、能力标签和生命周期。
- 校验参数，执行 Permission Check，调度 Handler，规范化 Tool Result。
- 提供超时、取消、资源限制、幂等、输出截断、工件落盘和审计 Hook。
- 统一内置工具、Skill 提供的工具与 MCP 动态工具。

为什么独立：工具是副作用边界，也是风险最高的执行入口。它必须与模型决策和具体 Handler 解耦。

### 2.2.5 Context Layer

职责：

- 计算 Token 预算并装配每次模型调用的最小上下文。
- 管理 System Prompt Sections、近期消息、Summary、任务/计划、工具结果、技能和检索片段。
- 触发历史裁剪、工具结果替换、分层压缩和 Prompt Snapshot。
- 输出 `ContextPackage` 和预算报告。

为什么独立：messages 不是简单列表，而是受模型窗口、成本、安全和恢复共同约束的派生视图。

### 2.2.6 Memory Layer

职责：

- 管理短期工作记忆与跨 Session 长期记忆。
- 从运行结果提取候选记忆，执行去重、敏感信息过滤和写入策略。
- 根据 tenant/user/project/task 范围进行检索、排序和注入。
- 记录来源、置信度、有效期和使用反馈。

为什么与 Context 分开：Memory 是持久知识，Context 是一次模型请求的临时输入。Context Manager 可以使用 Memory Retrieval，但不能拥有记忆的生命周期。

### 2.2.7 Storage Layer

职责：

- 为 Session、Task、Run、Step、Checkpoint、Approval、Memory、Trace、Audit 和 Eval 提供 Repository Port。
- 提供事务、乐观锁、Schema Migration、备份和保留策略。
- 提供 Artifact Store 保存大体积输出、Prompt Snapshot、补丁、测试报告等。
- 对上层隐藏 SQLite、文件系统及未来 PostgreSQL/对象存储差异。

为什么独立：一致性状态与大对象的存取特征不同，不能把所有内容塞进 messages、日志或单个 JSON 文件。

### 2.2.8 Observability Layer

职责：

- 采集 Log、Trace、Metric、Audit 和 Eval 数据。
- 生成并传播 trace/span/event ID。
- 对输入、Secret、工具参数和输出执行分级脱敏。
- 将同一事件投影到不同 Sink，而不是让业务模块重复记录。

为什么独立：调试日志、执行证据、安全审计和效果评估的保留期、权限和完整性要求不同。

## 2.3 调用关系与约束

```text
CLI -> RuntimeFacade
Runtime -> State Repositories
Runtime -> ContextManager -> MemoryRetriever / PromptCatalog / ToolRegistry
Runtime -> ModelClient
Runtime -> ToolExecutor -> PermissionEngine -> ToolHandler or MCPClient
Runtime -> CheckpointService
All application services -> EventPublisher -> Trace/Audit/Metric projectors
Adapters -> external SDK / OS / SQLite / files
```

约束：

1. CLI 不得直接调用 Tool Handler 或 Model SDK。
2. Tool Handler 不得直接修改 SessionState；它只返回 ToolResult 和 Artifact 引用。
3. PermissionEngine 不执行工具；ToolExecutor 不自行发明安全策略。
4. ContextManager 只读取记忆，不直接写长期 Memory。
5. Observability Sink 失败不能破坏主事务，但 Audit 持久化失败时高风险动作必须 fail closed。
6. Storage Adapter 不能包含 Plan/Reflect 等业务规则。
7. 所有跨层数据结构均带 `schema_version`，数据库主键使用不可猜测的全局 ID。

## 2.4 统一消息与事件协议

系统内部不传递无结构字符串。基础 Envelope 至少包含：

| 字段 | 含义 |
|---|---|
| `schema_version` | 协议版本 |
| `event_id` | 事件唯一 ID，用于去重 |
| `event_type` | 如 `user.input.received`、`tool.call.completed` |
| `timestamp` | UTC 时间 |
| `trace_id` / `span_id` / `parent_span_id` | 链路关联 |
| `tenant_id` / `user_id` | 身份与隔离边界；本地单用户也保留 |
| `session_id` / `task_id` / `run_id` / `step_id` | 业务关联 |
| `agent_id` | 事件所属 Agent |
| `causation_id` / `correlation_id` | 因果与请求响应关联 |
| `payload` | 版本化的事件负载 |
| `sensitivity` | 脱敏与保存级别 |

统一协议使 checkpoint、replay、Trace、Eval 和多 Agent 通信共用关联语义，但事件负载按领域拆分，避免形成万能 Event 对象。

---

# 3. Agent Runtime 核心流程

## 3.1 顶层状态机

```text
Input
  -> Session Recovery
  -> Context Assembly
  -> Plan
  -> Execute
  -> Observe
  -> Reflect / Verify
  -> Persist
       |-> continue -> Context Assembly
       |-> wait_for_approval / wait_for_event
       |-> completed / failed / cancelled
```

每个阶段输入、输出都是结构化对象；阶段转换先产生事件，再在事务内提交状态。模型不能任意跳转 Runtime 状态，只能通过受支持的响应类型表达建议动作。

## 3.2 Input

输入来源：

- 用户 CLI 输入；
- 人工审批/拒绝/补充指令；
- 后台工具完成通知；
- 定时触发；
- Subagent/Team 消息；
- 恢复命令或取消信号。

数据流：

1. CLI/事件适配器生成 `RuntimeInput`。
2. 校验身份、目标 Session、幂等键与 Schema。
3. 将原始输入保存为不可变 Event；敏感内容按策略另存或脱敏。
4. 创建或唤醒 Run，并为本次处理分配 trace。

为什么先持久化输入：若进程在处理期间崩溃，恢复时仍能区分“输入未处理”与“输入不存在”，也能对重复投递去重。

## 3.3 Session Recovery

恢复顺序：

1. 读取 Session 元数据和当前版本。
2. 获取最新有效 Checkpoint，并校验 hash、Schema 版本和所有 Artifact 引用。
3. 加载 Checkpoint 后发生的事件，按顺序重放到 RunState。
4. 读取 Task DAG、Pending Approval、后台 Job、Mailbox 和 Worktree 绑定。
5. 对 `executing` 工具调用执行不确定结果协调：
   - 有幂等查询能力：查询远端或 Handler 状态；
   - 可安全重试：使用相同 idempotency key 重试；
   - 无法确定：标记 `needs_reconciliation`，请求人工处理，绝不假设成功。
6. 验证工作区指纹、Git 分支/worktree 与 checkpoint 是否一致。
7. 生成 `RecoveryReport`，进入可运行、等待或人工协调状态。

为什么 checkpoint 之外还需事件重放：checkpoint 不必在每个细粒度事件后创建，尾部事件保证最新状态不丢失。

## 3.4 Context Assembly

输入：

- 恢复后的 SessionState/RunState；
- 当前目标、Task、Plan；
- 近期 Message 与 Session Summary；
- Tool Registry 当前快照；
- 检索到的 Memory/Knowledge/Skill；
- Policy 与模型窗口配置。

处理：

1. 计算固定预留：系统指令、工具 Schema、预期输出、模型响应和安全余量。
2. 对候选上下文按“必须项、相关性、时效性、可信度、成本”评分。
3. 必要时截断大工具结果，以 Artifact 摘要替代。
4. 若仍超预算，触发 Summary/Compaction，原始记录保留在 Transcript/Artifact。
5. 组装分区 Prompt 并保存不可变 `PromptSnapshot`。

输出：`ContextPackage { messages, tools, prompt_snapshot_ref, token_budget_report, provenance[] }`。

为什么保存 provenance：后续可以解释某条记忆或文档为什么进入 Prompt，并支持 Eval 复现。

## 3.5 Plan

Plan 是显式阶段，不要求每个简单输入都生成复杂计划。

1. `PlanningPolicy` 根据任务复杂度、风险、剩余预算决定 `direct` 或 `planned`。
2. planned 模式调用模型生成结构化 `Plan`：目标、步骤、依赖、验收条件、风险、预算。
3. Runtime 校验计划约束：最大步骤、允许工具、不可满足依赖和是否需要人工确认。
4. 计划写入 RunState；跨 Session 的工作可投影为持久 Task DAG。

Plan 与 Task 的区别：

- Plan 是当前 Run 内可修订的执行策略。
- Task 是跨 Run/Session 持久的工作项及依赖。

这样设计避免把临时推理步骤误当作长期任务，也允许 Reflect 局部修订计划而不改写任务历史。

## 3.6 Execute

1. 根据 Plan 选择下一个可执行 Step。
2. 创建 StepState 并在外部动作前保存 `intent checkpoint`。
3. 调用 ModelClient。
4. 处理归一化响应：
   - `assistant_message`：候选最终回答或中间说明；
   - `tool_calls`：一个或多个结构化调用；
   - `plan_update`：请求修订计划；
   - `clarification_request`：需要用户信息；
   - `delegate_request`：请求 Subagent；
   - `stop`：因预算、策略或错误停止。
5. 对工具调用按依赖关系分组；只读且相互独立的调用可并发，有副作用的调用默认串行。

模型调用前后的配置、Prompt Snapshot、Usage、耗时和归一化输出均进入 Trace。

## 3.7 Observe

Observe 将外部事实转为统一 Observation：

- Tool 成功、失败、拒绝或等待审批；
- 模型 Provider 错误；
- 测试/验证结果；
- 后台任务状态；
- 用户/队友反馈；
- 预算、超时或取消事件。

`Observation` 包含状态、摘要、结构化数据、Artifact 引用、可重试性、风险和来源。原始大输出不直接永久放入 messages；messages 使用有界摘要和引用。

为什么“拒绝”也是结果：模型必须知道动作没有发生，才能改变方案；否则容易产生错误的成功假设。

## 3.8 Reflect / Verify

Reflect 先执行确定性验证，再按需调用模型：

1. 根据步骤验收条件执行规则检查，如退出码、文件存在、测试结果、目标字段。
2. `VerificationResult` 判断事实是否满足。
3. Reflect 结合 Observation 和剩余预算选择：
   - `continue`：进入下一步；
   - `revise_plan`：修订未完成步骤；
   - `retry`：仅对可重试错误，应用次数与退避限制；
   - `request_approval` / `request_user_input`；
   - `delegate`；
   - `complete`；
   - `fail` / `cancel`。
4. 对最终完成必须有显式 Completion Criteria；不能仅凭模型声称“完成”。

为什么确定性验证优先：测试退出码、Schema、文件 hash 等事实不需要模型判断，可降低成本并减少幻觉。

## 3.9 Persist

Persist 在单个本地事务中完成：

1. 追加领域事件和 Trace 元数据；
2. 更新 Session/Run/Step/Task/Approval 投影及版本；
3. 保存新的 Message、Summary、Memory Candidate 和 Eval 引用；
4. 在策略边界创建 Checkpoint；
5. 提交事务后发布非关键通知和刷新指标。

建议 checkpoint 边界：

- 接收并持久化新输入后；
- 计划确认后；
- 有副作用工具执行前；
- 工具结果写回后；
- 进入/退出等待审批；
- Run 完成、失败、取消时；
- 每 N 个 Step 或上下文压缩后。

工件文件采用“先写临时文件并 fsync/原子重命名，再提交数据库引用”；数据库失败时孤立工件可由 GC 清理。高风险 Audit 必须与动作意图在执行前持久化。

---

# 4. 状态管理设计

## 4.1 分层原因

Session、Run、Step 和 Checkpoint 的更新频率、恢复语义与保留周期不同。全部塞进一个状态对象会导致：

- 每次工具输出都重写整个 Session；
- 无法区分跨会话事实和一次运行的瞬时重试；
- 恢复时不知道副作用发生在哪个边界；
- 并行 Agent 更容易覆盖彼此状态；
- Trace/Eval 无法准确定位失败层级。

因此采用四级状态，并由 ID 和版本关联。

## 4.2 SessionState

保存内容：

| 类别 | 字段示例 |
|---|---|
| 身份 | `session_id`、`tenant_id`、`user_id`、`project_id` |
| 生命周期 | `status`、`created_at`、`updated_at`、`last_active_at` |
| 对话视图 | `message_cursor`、`summary_ref`、`active_run_id` |
| 默认配置 | `agent_profile`、`model_policy_ref`、`permission_profile_ref` |
| 工作区 | `workspace_root`、`workspace_fingerprint` |
| 恢复 | `latest_checkpoint_id`、`state_version` |

生命周期：

```text
created -> active <-> suspended -> archived
                    \-> corrupted / needs_migration
```

Session 跨多个用户回合和 Run 存在。归档不立即删除 Trace、Audit 或 Eval。

恢复方式：加载 Session snapshot、最新 Checkpoint、尾部消息/事件，并验证工作区与 pending 状态。

为什么需要：它是对话、身份、配置和隔离边界，不应包含某次模型重试的细节。

## 4.3 RunState

一个 Run 表示一次输入或事件驱动的完整处理过程。

保存内容：

| 类别 | 字段示例 |
|---|---|
| 关联 | `run_id`、`session_id`、`task_id`、`agent_id`、`trace_id` |
| 触发 | `input_event_id`、`trigger_type` |
| 阶段 | `phase`、`status`、`current_step_id` |
| 计划 | `plan`、`plan_version`、`completion_criteria` |
| 预算 | `max_steps`、`deadline`、`token_budget`、`cost_budget`、累计 Usage |
| 可靠性 | `retry_counters`、`last_error`、`cancel_requested` |
| 等待 | `pending_approval_id`、`waiting_event_type` |

生命周期：

```text
queued -> recovering -> running
running -> waiting_approval / waiting_input / waiting_event
waiting_* -> recovering -> running
running -> completed / failed / cancelled / exhausted
```

恢复方式：从 Run snapshot 恢复阶段与预算，再重放 checkpoint 后的 Step/Event；等待态通过 Approval/Event 唤醒。

为什么需要：Run 是成本、超时、最终结果和 Trace 的主要统计边界。

## 4.4 StepState

一个 Step 表示一次可独立观察和验证的状态转换，通常对应模型调用、工具调用、验证或委派。

保存内容：

- `step_id`、`run_id`、`parent_step_id`、`sequence_no`；
- `step_type`：plan/model/tool/verify/reflect/delegate；
- `status`：pending/executing/succeeded/failed/waiting/skipped/unknown；
- 输入摘要与 Artifact 引用；
- `tool_call_id` 或 `model_call_id`；
- Permission Decision 与 Approval 引用；
- Observation、VerificationResult；
- attempt、开始/结束时间、错误类别、Usage；
- 幂等键与副作用等级。

生命周期：

```text
pending -> executing -> succeeded / failed / waiting / unknown
waiting -> executing
failed -> pending（仅创建新 attempt，不覆盖旧记录）
```

恢复方式：已终态 Step 不重复执行；executing Step 根据幂等性和外部状态进入查询、重试或人工协调。

为什么需要：它是恢复与诊断的最小业务单元，不能只依赖日志推断。

## 4.5 Checkpoint

Checkpoint 是一致、版本化、可校验的恢复快照，不是完整审计记录。

保存内容：

- `checkpoint_id`、`session_id`、`run_id`、`sequence_no`；
- `checkpoint_type`：periodic/pre_side_effect/post_side_effect/waiting/terminal；
- `state_schema_version`、Runtime 版本；
- Session/Run/必要 Step 的 snapshot；
- message/event cursor 与 Summary 引用；
- Plan 版本、Task 版本；
- Pending Approval、后台 Job、Mailbox cursor；
- Prompt/Tool Registry/Model/Policy 配置版本；
- Workspace/Git 指纹；
- Artifact manifest 与内容 hash；
- `created_at`、`checksum`、`previous_checkpoint_id`。

生命周期：创建后不可修改；可标记 invalid/superseded，但不得覆盖。保留最近 N 个、所有等待/副作用/终态 checkpoint，以及 Audit 引用的 checkpoint。

恢复算法：

1. 选择最新 checksum 有效且 Schema 可迁移的 checkpoint；
2. 校验依赖 Artifact；
3. 必要时回退到上一个 checkpoint；
4. 重放 cursor 之后的事件；
5. 协调未终态副作用；
6. 创建新的 `recovery` checkpoint 后继续。

## 4.6 一致性、并发与幂等

- Session/Run 使用 `state_version` 做乐观锁；更新条件为旧版本匹配。
- 单 Session 默认只允许一个前台 Run 修改对话顺序；后台 Job 通过 Event 回注入，不直接改 messages。
- Task claim、Mailbox ack、Approval resolve 使用数据库事务和唯一约束。
- 外部副作用使用稳定 `idempotency_key = hash(run_id, step_id, attempt_scope)`。
- Tool Result 写入以 `tool_call_id` 唯一，重复结果做幂等合并。
- 状态迁移由集中 `StateTransitionService` 校验，Repository 不接受任意 status 更新。

---

# 5. Tool 系统设计

## 5.1 Tool Schema

模型可见 Schema 与 Runtime 元数据分离。

模型可见部分：

- `name`、`description`；
- `input_schema`（JSON Schema）；
- 可选 `output_schema`；
- 使用约束的简短说明。

Runtime 元数据：

- `tool_id`、`namespace`、`version`、`source`（builtin/skill/mcp）；
- `capabilities`（filesystem.read、filesystem.write、process.exec、network 等）；
- `side_effect`（none/read/write/destructive/external）；
- `risk_level`、默认 timeout、最大输出、并发策略；
- `idempotency`（safe/idempotent/non_idempotent/queryable）；
- `availability`、平台要求、配置依赖；
- `permission_requirements`、敏感字段路径；
- Handler/Adapter 引用。

为什么分离：模型不需要看到内部风险和实现细节，但 Permission 和 Executor 必须使用可信元数据，不能相信模型自报风险。

## 5.2 Tool Registry

Registry 提供：

- `register(descriptor, handler_ref)`；
- `unregister/disable`；
- 按名称、版本、能力、来源查询；
- 生成当前 Run 的模型可见工具快照；
- 名称冲突与版本兼容检查；
- 健康状态、连接状态和生命周期管理。

命名建议：

- 内置：`fs.read_file`；
- Skill：`skill.<skill_name>.<tool>`；
- MCP：`mcp.<server_alias>.<tool>`。

Registry 在 Context Assembly 时产出不可变 `ToolCatalogSnapshot`。Run 中途发生工具发现变化，不自动改变正在执行的请求；下一轮显式刷新，保证 Prompt 与实际可调用集合一致。

## 5.3 Tool Executor

统一执行管线：

```text
ToolCall
 -> Resolve descriptor/version
 -> Validate input schema
 -> Canonicalize path/host/command
 -> Permission Check
 -> [allow | deny | pending approval]
 -> Pre-execution checkpoint
 -> Acquire limits/locks
 -> Handler or MCP invocation
 -> Normalize result
 -> Redact + truncate + artifact persist
 -> Post hooks + audit + metrics
 -> ToolResult
```

Executor 负责超时、取消、异常归一化和资源释放。Handler 只负责工具业务能力，不负责审批、Trace 或消息回填。

## 5.4 Permission Check

Permission 输入必须包含：

- 主体：tenant/user/agent/session；
- 工具：可信 Tool Descriptor；
- 动作：规范化参数和 capability；
- 资源：解析后的绝对路径、host、命令、工作区；
- 上下文：Task、风险、是否交互、历史批准范围；
- 环境：平台、配置 profile、资源预算。

决策结果：

```text
ALLOW      允许一次执行，可附加约束
DENY       拒绝并说明可安全展示的原因
APPROVAL   创建持久 ApprovalRequest，暂停 Step
```

策略优先级：硬安全边界 > 明确 deny > 临时审批授权 > profile allow > 默认策略。审批不能绕过不可变硬边界，如路径越界或 Secret 导出禁令。

审批对象保存参数摘要、精确能力范围、过期时间、一次性/Session 范围和审批者。执行前再次校验参数 hash，防止“审批 A、执行 B”。

## 5.5 Tool Result

统一 `ToolResult` 包含：

| 字段 | 含义 |
|---|---|
| `tool_call_id` / `tool_id` / `tool_version` | 调用关联 |
| `status` | succeeded/failed/denied/pending/cancelled/timed_out/unknown |
| `summary` | 给模型的有界结果 |
| `structured_content` | 通过输出 Schema 校验的数据 |
| `artifact_refs` | 完整输出、补丁、报告等 |
| `error` | 归一化错误类别、可重试性、安全消息 |
| `metrics` | duration、bytes、exit_code 等 |
| `truncated` | 是否截断及原文引用 |
| `side_effect_record` | 已知发生的副作用摘要 |

输出中 Secret 和敏感字段先脱敏再进入 Log/Model；受访问控制的原始工件按保存策略落盘。

## 5.6 无需修改 Agent Loop 的扩展机制

新增工具只需要：

1. 实现统一 Handler Port 或 MCP Adapter；
2. 提供版本化 Tool Descriptor 与 JSON Schema；
3. 声明 capability、风险、幂等和资源限制；
4. 在 Registry 注册；
5. 提供 Permission Policy 和契约测试。

Agent Loop 只处理通用 `ToolCall -> ToolExecutor -> ToolResult`。工具类型差异由 Descriptor 与 Handler 解决，因此新增工具不会增加主循环 `if/elif` 分支。

---

# 6. Context 和 Memory 设计

## 6.1 Context Manager

### 6.1.1 Token 预算

每次请求的预算：

```text
model_context_window
- reserved_output_tokens
- system_and_policy_tokens
- tool_schema_tokens
- safety_margin
= available_dynamic_context
```

动态上下文再按策略分配给：当前输入、近期对话、计划/任务、工具观察、Summary、Memory、Skill 和 Retrieval。必须项先分配，其他候选按分数选择。

预算报告记录估算器版本、各区块 Token、被剔除项和压缩原因。Provider 返回的实际 Usage 用于校准估算器。

### 6.1.2 历史压缩

按低损失到高损失顺序执行：

1. 删除重复或不可见的 UI 事件；
2. 将超大 Tool Result 替换为摘要 + Artifact 引用；
3. 合并连续低价值状态消息；
4. 保留系统约束、当前输入、未解决审批和最近关键往返；
5. 对较旧消息生成分层 Summary；
6. 极端情况下创建新的会话段，并保留完整 Transcript。

任何压缩都不能删除尚未闭合的 tool call/result 对、待执行计划约束或安全决策。

### 6.1.3 Summary

Summary 是带 Schema 的派生数据，不是一段无来源文本。建议字段：

- 用户目标与已确认约束；
- 已完成工作及证据；
- 当前计划和未完成项；
- 关键文件/实体/决策；
- Tool 结果和错误摘要；
- 待审批、风险和下一步；
- 来源 Message/Event 范围；
- Summary 版本、生成模型、置信度。

新 Summary 通过覆盖消息范围与 checksum 关联原文；原文仍保存在 Transcript/Artifact，可供审计和重建。

### 6.1.4 Context Assembly 顺序

推荐 Prompt Sections：

1. Runtime 身份与不可变安全规则；
2. Agent profile 与任务特定指令；
3. Workspace/平台/时间等环境事实；
4. 当前目标、Plan、Task 和状态；
5. Session Summary 与近期消息；
6. 按需 Memory、Skill、Knowledge；
7. Tool Schema；
8. 当前输入与要求的响应协议。

Section 带名称、版本、优先级和来源。最终 Prompt 保存 Snapshot，便于 Diff、A/B 和 replay。

## 6.2 Memory

### 6.2.1 短期记忆

范围为当前 Session 或 Run，包括：

- 近期 messages；
- Session Summary；
- 当前 Plan、未解决问题、临时实体和偏好；
- 近期 Tool Observation。

短期记忆可压缩、替换，不承诺跨 Session 长期保留。它由 Context/Session 管理，不等同于长期 Memory Store。

### 6.2.2 长期记忆

候选类型：

- 用户明确偏好；
- 项目稳定约定和架构决策；
- 经验证的事实与环境信息；
- 可复用的任务经验和失败教训；
- 显式要求保存的内容。

每条 Memory 包含 `memory_id`、scope、type、content/embedding、source refs、confidence、sensitivity、created/last_used、valid_from/to、supersedes、status。

不应自动保存：Secret、临时错误、未经验证的模型推断、完整敏感对话和与任务无关的个人数据。

### 6.2.3 Retrieval

检索流水线：

```text
query generation
 -> scope/ACL filter
 -> lexical + semantic candidate retrieval
 -> recency/trust/task relevance rerank
 -> deduplicate/conflict detection
 -> token budget selection
 -> provenance package
```

Phase 2 可先使用 SQLite FTS/关键词检索；向量检索作为可替换 `MemoryIndex Port` 在后续加入。

### 6.2.4 Injection

Memory 不伪装成 system rule，应以明确的“检索到的历史信息”区块注入，并携带来源、时间和可信度。冲突时优先级为：当前用户明确指令 > 项目权威文件 > 经验证的新事实 > 长期记忆 > 模型推断。

### 6.2.5 写入与治理

运行结束后 `MemoryExtractor` 只生成 Candidate；`MemoryPolicy` 执行敏感过滤、去重、合并、TTL 和是否需要人工确认。使用反馈更新 `last_used` 和 usefulness，不直接篡改原始来源。

为什么分两步：模型提取可能包含幻觉或敏感数据，不能直接写入长期记忆。

---

# 7. Multi Agent 设计

## 7.1 Agent

Agent 是一个拥有独立身份、profile、权限、模型策略和 Context 的 Runtime 实例。核心字段：

- `agent_id`、role（lead/worker/specialist）；
- `parent_agent_id`、team_id；
- capability/permission profile；
- 独立 session/run/message cursor；
- Task assignment 与 workspace/worktree 绑定；
- 状态：starting/idle/working/waiting/stopping/stopped/failed。

## 7.2 Subagent

Subagent 是由父 Agent 为有界子任务创建的独立 Agent：

- 输入只包含任务说明、验收标准、允许资源和最小必要上下文；
- 不自动继承父 Agent 全部对话、Memory 或 Secret；
- 拥有独立 Run、Token/成本/步数预算；
- 通过结构化 `SubagentResult` 返回摘要、证据、Artifact 和未解决风险；
- 父 Agent 负责验收，不把子 Agent 的“完成”直接当作最终事实。

为什么独立上下文：减少主上下文污染，限制信息暴露，并能单独预算、取消和诊断。

## 7.3 Team

Team 由 Lead、Workers、共享 Task Board、Mailbox 和 Workspace Isolation 组成。

- Lead：拆分目标、建立依赖、处理异常、验收和整合。
- Worker：在权限允许时认领 ready Task，完成后回到 idle。
- Task claim 必须事务化，防止重复执行。
- 文件修改任务绑定 Git branch/worktree；`owner` 解决“谁负责”，worktree 解决“在哪里改”。
- 合并、删除 worktree 或丢弃改动属于显式高风险流程，不能因 Task complete 自动发生。

## 7.4 Communication Protocol

消息 Envelope 复用统一事件字段，并增加：

- `message_id`、`from_agent_id`、`to_agent_id/team_id`；
- `message_type`：inform/request/response/command/cancel/heartbeat；
- `request_id`、`reply_to`；
- `delivery_mode`、`expires_at`；
- `payload_schema`、`payload`；
- `ack_status`、`dedup_key`。

request-response 状态机：

```text
created -> delivered -> acknowledged -> responded
        \-> expired / cancelled / rejected
```

Mailbox 使用 durable store；至少一次投递，消费者用 `message_id` 去重。Heartbeat 仅表示进程活性，不等于 Task 进度。

## 7.5 上下文隔离

- 每个 Agent 只读自己的 messages、RunState 和私有 Memory scope。
- Team 共享的只有 Task、显式发布的 Artifact/Message 和受控 workspace。
- Context Transfer 采用 manifest：每项都有来源、敏感级别、允许接收者和 hash。
- Tool 权限以 Agent 身份重新判断，不能继承父 Agent 某次审批。
- 子 Agent 输出先经过脱敏和预算压缩，再注入父 Agent Context。

## 7.6 并发与失败

- Team Scheduler 设置最大并发、模型配额、工具锁和 workspace 锁。
- Agent 崩溃后 lease 超时，Task 进入 recovery，不立即被其他 Worker 重做副作用步骤。
- Lead 停止采用 request/ack 协议；超时后再由 Runtime 强制取消。
- 循环委派通过最大深度、祖先链和预算限制阻止。

---

# 8. MCP 接入设计

## 8.1 MCP Client

MCP Client Adapter 负责：

- 根据配置启动或连接 Server；
- initialize 与能力协商；
- 获取 tools/resources/prompts 能力；
- `tools/list`、`tools/call`；
- 连接健康、超时、取消、重连和错误归一化；
- 对认证信息进行 Secret 注入而非写入 Prompt。

Runtime 不直接依赖 MCP SDK，只依赖 `ExternalToolProvider Port`。

## 8.2 MCP Server

本项目作为 Host 时不信任外部 Server。每个 Server 配置包含：

- 稳定 alias、transport、启动命令或 endpoint；
- 允许的环境变量白名单；
- 信任级别、默认权限 profile；
- 启动/调用 timeout、并发上限；
- 工具 allow/deny 列表；
- Schema 缓存 TTL 与认证引用。

若未来本项目暴露 MCP Server，则由独立 Adapter 将内部受控能力映射出去，不复用 CLI 身份隐式授权。

## 8.3 Tool Discovery

```text
Connect
 -> Initialize/capability negotiation
 -> tools/list
 -> Validate and normalize schema
 -> Apply server/tool policy
 -> Namespace names
 -> Registry staging
 -> Atomic publish ToolCatalogSnapshot
```

发现失败只影响该 Server，不应破坏内置工具。Schema 非法、名称冲突或能力超出策略的工具进入 quarantine，并生成诊断事件。

## 8.4 Dynamic Tool Registration

- MCP 工具注册为 `mcp.<server_alias>.<tool_name>`。
- Descriptor 保存 Server、远端工具名、Schema hash 和发现版本。
- 新 catalog 原子替换，正在执行的 Run 继续使用原快照。
- 工具下线后，新调用不可见；已持久化调用仍能通过版本信息解释。
- Schema 发生破坏性变更时创建新版本，不静默覆盖。

## 8.5 MCP 调用安全

所有 MCP 调用仍经过本地 ToolExecutor：

```text
Model ToolCall
 -> local schema validation
 -> local PermissionEngine
 -> audit intent
 -> MCPClient tools/call
 -> result size/type validation
 -> redaction/artifact
 -> normalized ToolResult
```

MCP Server 的描述和结果都属于不可信外部输入，不能改变 system policy，也不能绕过本地路径、网络、超时和审批限制。

---

# 9. Persistence 设计

## 9.1 存储分工

```text
SQLite
  事务状态、索引、事件元数据、引用、审批、任务与投影

Artifact Store（本地内容寻址目录）
  大工具输出、Prompt Snapshot、Transcript、补丁、测试报告、Eval 样本

Rolling Log / JSONL
  人类实时排障日志；不是业务状态真相来源
```

本地目录建议位于项目数据目录且加入 `.gitignore`。Secret 不进入数据库明文；仅保存 Secret reference。

## 9.2 Session

核心结构：

```text
sessions(
  session_id, schema_version, tenant_id, user_id, project_id,
  status, agent_profile, model_policy_ref, permission_profile_ref,
  workspace_root, workspace_fingerprint,
  active_run_id, latest_checkpoint_id, state_version,
  created_at, updated_at, archived_at
)
```

关联 `messages` 表保存 role/type/content_ref/sequence/token estimate。大内容通过 Artifact reference 保存。

## 9.3 Task

```text
tasks(
  task_id, parent_task_id, session_id, team_id,
  title, description_ref, status, priority,
  owner_agent_id, lease_until, workspace_ref,
  acceptance_criteria_ref, result_ref,
  state_version, created_at, updated_at
)
task_dependencies(task_id, depends_on_task_id, dependency_type)
```

状态建议：draft/ready/claimed/in_progress/blocked/waiting_review/completed/failed/cancelled。依赖图写入时检查环；claim 使用事务和 lease。

## 9.4 Checkpoint

```text
checkpoints(
  checkpoint_id, session_id, run_id, sequence_no, type,
  state_schema_version, runtime_version,
  snapshot_ref, event_cursor, message_cursor,
  workspace_fingerprint, manifest_ref, checksum,
  previous_checkpoint_id, status, created_at
)
```

Checkpoint 行和 Artifact manifest 都不可变。恢复优先最新 valid，校验失败自动回退并生成 Audit/Trace 事件。

## 9.5 Trace

Trace 采用 trace + span：

```text
traces(trace_id, session_id, run_id, root_span_id, status,
       started_at, ended_at, total_tokens, estimated_cost, result_ref)
spans(span_id, trace_id, parent_span_id, kind, name, status,
      started_at, ended_at, attributes_ref, input_ref, output_ref, error_ref)
events(event_id, trace_id, span_id, event_type, sequence_no,
       payload_ref, sensitivity, timestamp)
```

Span kind 包括 runtime/model/tool/permission/checkpoint/retrieval/subagent。payload 大于阈值时使用 Artifact ref。

## 9.6 Audit

```text
audit_records(
  audit_id, event_id, actor_type, actor_id,
  action, resource_type, resource_id,
  decision, policy_id, policy_version,
  request_hash, reason_code, approval_id,
  before_ref, after_ref, trace_id, timestamp,
  integrity_hash
)
```

Audit append-only；修改只能追加 correction。记录安全相关事实而非完整敏感内容。高风险工具执行前，Audit intent 持久化失败则拒绝执行。

## 9.7 Eval

```text
eval_cases(
  eval_case_id, source_run_id, dataset_id, input_ref,
  expected_outcome_ref, grading_rubric_ref, tags, created_at
)
eval_runs(
  eval_run_id, eval_case_id, runtime_version,
  model_config_ref, prompt_snapshot_ref, tool_catalog_ref,
  replay_mode, status, result_ref, metrics_ref, created_at
)
eval_scores(
  eval_run_id, metric_name, metric_version,
  numeric_value, label, evidence_ref, grader_type, grader_ref
)
```

Eval replay 默认 mock 或只读工具。带外部副作用的真实重放必须使用隔离环境和显式授权。

## 9.8 其他关键表

- `runs`、`steps`：保存第 4 节状态投影；
- `tool_calls`、`model_calls`：调用级事实与 Usage；
- `approvals`：pending/resolved/expired 与精确 request hash；
- `memories`、`memory_sources`、`memory_usage`；
- `mailbox_messages`、`background_jobs`；
- `schema_migrations`、`outbox_events`。

`outbox_events` 用于事务提交后可靠发布通知：状态和待发布事件同事务写入，后台投递成功后 ack。

## 9.9 数据保留与迁移

- Session/Task/Checkpoint：用户归档或配置保留期；
- Trace：中期保留，可压缩；
- Audit：最长保留并限制访问；
- Log：最短保留、滚动清理；
- Eval：版本化数据集长期保留；
- Artifact：引用计数 + 保留策略 + 延迟 GC。

Schema 迁移只向前执行；Checkpoint payload 通过版本迁移器读取。破坏性升级前创建备份和兼容性检查，不在启动时静默丢弃未知字段。

---

# 10. Observability 设计

## 10.1 Log、Trace、Audit、Eval 的区别

| 类型 | 回答的问题 | 主要受众 | 典型内容 | 可否采样 | 完整性要求 |
|---|---|---|---|---|---|
| Log | 进程现在发生了什么，如何排障？ | 开发/运维 | DEBUG、异常栈、重试、连接状态 | 可以 | 最佳努力 |
| Trace | 一次 Run 的完整执行链是什么？ | 开发/分析 | Model/Tool Span、耗时、Token、事件因果 | 可对低价值细节采样 | Run 关键链路不可缺 |
| Audit | 谁在什么策略下允许/拒绝了什么？ | 安全/合规 | 权限判断、审批、人工干预、高风险动作 | 不可以 | append-only、可校验 |
| Eval | Agent 做得好不好，版本变化是否改善？ | 产品/研发 | 输入、配置快照、结果、评分、成本、证据 | 数据集策略决定 | 必须可复现、可比较 |

四者可引用同一个 Event/Artifact，但不能写进同一无边界文件，因为访问权限、保留期和查询方式不同。

## 10.2 Log

- 控制台使用适合人的简洁格式；文件使用结构化 JSONL。
- 支持 DEBUG/INFO/WARNING/ERROR 和 `--log-level`。
- 每条记录带 timestamp、level、logger、trace/session/run/step ID、event_type。
- Secret、`.env` 值、Authorization、敏感 Tool 字段统一通过 `RedactionService`。
- 不把完整 Prompt、文件内容或长 Tool 输出直接写日志。

## 10.3 Trace

根 Span 对应 Run，子 Span 对应 Recovery、Context、Model、Tool、Reflect、Persist。采集：

- Provider/model/config 版本；
- Prompt Snapshot ref；
- Tool/Policy 版本；
- 输入输出摘要与 Artifact；
- Token、估算成本、首 Token/总延迟；
- 重试、错误分类、checkpoint；
- Subagent link。

跨 Agent 不强制共享 parent-child 调用栈；使用 span link 和 correlation ID 表达异步因果。

## 10.4 Audit

必须审计：

- Permission allow/deny/approval；
- Approval 创建、查看、批准、拒绝、过期；
- 高风险 Tool 意图与结果；
- 人工修改计划/任务/状态；
- Memory 删除、数据导出、配置和策略变更；
- Worktree 清理、外部消息和服务认证变化。

Audit reason 使用稳定 reason code 加可读说明。审计失败时：只读低风险操作可按配置继续，高风险动作 fail closed。

## 10.5 Eval

Eval 分三类：

1. **离线回归**：固定输入、Fake/Replay Tool，比较 Prompt/模型/Runtime 版本。
2. **Shadow replay**：使用历史 Trace 构造无副作用重放，不影响真实状态。
3. **人工反馈**：用户评分、纠正和完成验收进入 Eval Evidence。

核心指标：

- 任务成功率、步骤成功率；
- 工具选择/参数正确率；
- 权限违规与不必要审批率；
- Token、成本、端到端延迟；
- 重试次数、恢复成功率；
- Context 压缩后信息保真度；
- Subagent 协作和任务重复率。

模型评分只能作为一项指标，关键任务应有确定性验证或人工标签。

## 10.6 指标与告警

本地阶段至少提供聚合统计：

- run_total/by_status；
- model_calls、tool_calls/by_status；
- approval_pending；
- recovery_total/by_outcome；
- token/cost/duration；
- context_compaction_total；
- queue/job depth。

Phase 4 通过 `MetricsSink Port` 接入生产监控。指标标签禁止使用 session_id 等高基数字段。

---

# 11. 模块目录结构

推荐采用 `src` 布局：

```text
local-dev-agent/
├─ src/local_dev_agent/
│  ├─ cli/
│  │  ├─ commands/              # start/resume/approve/trace 等
│  │  ├─ renderers/             # 终端输出与流式显示
│  │  └─ entrypoint.py
│  ├─ runtime/
│  │  ├─ loop.py                # 顶层阶段编排，不含基础设施细节
│  │  ├─ facade.py              # CLI/API 的统一应用入口
│  │  ├─ phases/                # recovery/context/plan/execute/observe/reflect/persist
│  │  ├─ policies/              # 预算、重试、完成、调度策略
│  │  └─ recovery/              # checkpoint 恢复与副作用协调
│  ├─ domain/
│  │  ├─ state/                 # Session/Run/Step/Checkpoint
│  │  ├─ messages/              # 内部 Message/Event 协议
│  │  ├─ tasks/                 # Task DAG 与状态机
│  │  ├─ approvals/
│  │  └─ errors/
│  ├─ models/
│  │  ├─ ports.py               # ModelClient 抽象
│  │  ├─ schemas.py
│  │  ├─ routing.py
│  │  └─ providers/
│  │     ├─ anthropic.py
│  │     ├─ openai.py           # 后续
│  │     └─ fake.py             # 测试
│  ├─ tools/
│  │  ├─ schemas.py
│  │  ├─ registry.py
│  │  ├─ executor.py
│  │  ├─ permissions/
│  │  ├─ hooks/
│  │  └─ builtin/
│  │     ├─ filesystem/
│  │     ├─ shell/
│  │     └─ todo/
│  ├─ context/
│  │  ├─ manager.py
│  │  ├─ budget.py
│  │  ├─ compaction.py
│  │  ├─ summary.py
│  │  └─ prompts/
│  ├─ memory/
│  │  ├─ service.py
│  │  ├─ extraction.py
│  │  ├─ retrieval.py
│  │  └─ policies.py
│  ├─ agents/
│  │  ├─ service.py
│  │  ├─ subagents.py
│  │  ├─ teams.py
│  │  ├─ mailbox.py
│  │  └─ scheduling.py
│  ├─ mcp/
│  │  ├─ client.py
│  │  ├─ discovery.py
│  │  ├─ registration.py
│  │  └─ adapters/
│  ├─ storage/
│  │  ├─ ports.py               # Repository/UnitOfWork/ArtifactStore
│  │  ├─ sqlite/
│  │  ├─ artifacts/
│  │  └─ migrations/
│  ├─ observability/
│  │  ├─ events.py
│  │  ├─ logging.py
│  │  ├─ tracing.py
│  │  ├─ audit.py
│  │  ├─ metrics.py
│  │  └─ redaction.py
│  ├─ eval/
│  │  ├─ datasets.py
│  │  ├─ runner.py
│  │  ├─ graders.py
│  │  └─ reports.py
│  ├─ config/
│  │  ├─ loader.py
│  │  ├─ schemas.py
│  │  └─ secrets.py
│  └─ shared/
│     ├─ ids.py
│     ├─ clock.py
│     └─ serialization.py
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ contract/                 # Provider/Tool/MCP/Repository 契约
│  ├─ recovery/                 # 崩溃点与 checkpoint 测试
│  ├─ security/
│  ├─ eval/
│  └─ fixtures/
├─ prompts/                     # 版本化 Prompt 模板与元数据
├─ policies/                    # 默认权限/预算策略
├─ evals/                       # 数据集、rubric，不存运行 Secret
├─ docs/
│  ├─ adr/                      # 关键架构决策记录
│  ├─ protocols/
│  └─ operations/
├─ var/                         # 本地运行数据，加入 .gitignore
│  ├─ agent.db
│  ├─ artifacts/
│  ├─ logs/
│  └─ backups/
├─ TDD.md
└─ HANDOFF.md
```

目录职责约束：

- `domain` 不依赖 `cli`、Provider SDK、SQLite 或 MCP。
- `runtime/phases` 可以依赖各 Port，不能导入具体 Adapter。
- `tools/builtin` 不包含权限决策。
- `observability` 不反向驱动业务状态；Audit 的 fail-closed 通过 Port 返回明确结果。
- `shared` 只放真正通用的小型基础类型，避免成为万能模块。
- 每个 Provider、Tool 和 Repository 都必须有契约测试。

---

# 12. 开发路线

路线以“每一阶段都形成可验证闭环”为原则。后续阶段可以增加 Adapter 和服务，不改变前一阶段已稳定的核心协议。

## Phase 1：可靠单 Agent 闭环

范围：Agent Loop、Tool、Permission、State。

### 目标

- 完成单 Session、多轮 CLI 对话。
- Anthropic Provider 通过统一 Model Port 接入。
- 实现 Tool Schema/Registry/Executor 和至少只读文件、受控 Shell/Todo 工具。
- Permission 支持 allow/deny/approval；审批可持久化并恢复。
- 建立 SessionState、RunState、StepState 和基础 SQLite Repository。
- 建立统一 Message/Event/Tool Result 协议。
- 提供结构化 Log、基础 Trace/Audit、超时与错误分类。

### 关键验收

1. Fake Model 可以驱动“模型 -> ToolCall -> ToolResult -> 模型 -> 完成”的确定性集成测试。
2. 新增测试工具只注册 Descriptor/Handler，不修改 Agent Loop。
3. 路径越界与危险命令在 Handler 前被拒绝。
4. 需要审批的调用重启 CLI 后仍可批准/拒绝并继续。
5. 每个 Run 可通过 trace_id 还原模型、工具、权限和结果链路。
6. Provider 超时、限流、无效 Tool 参数均有归一化错误和有界重试。

### 明确不做

- 长期 Memory、自动压缩、Subagent、MCP、并发 Team、Web/API。

## Phase 2：可持续工作与恢复

范围：Checkpoint、Context、Memory。

### 目标

- 实现 pre/post side-effect Checkpoint 与崩溃恢复。
- Context Manager 支持 Token 预算、Tool 输出 Artifact 化、历史压缩和 Summary。
- Prompt Section/Version/Snapshot 可追溯。
- 短期/长期 Memory 分离，提供提取、策略、SQLite FTS Retrieval 和 Injection。
- Task DAG 支持跨 Session 推进。
- 增加后台 Job/Event 回注入的最小能力。

### 关键验收

1. 在工具执行前、执行后、结果提交前模拟崩溃，恢复不会静默重复非幂等副作用。
2. 长对话在预算内组装；被压缩内容仍能通过 Transcript/Artifact 追溯。
3. Prompt Snapshot 可复现某次 Model Request。
4. 长期记忆严格按 scope/ACL 检索，不注入其他 Session/Project 的私有数据。
5. Task DAG 与 Plan 边界清晰，完成状态有验收证据。

## Phase 3：能力扩展与协作

范围：Subagent、MCP、Multi Agent。

### 目标

- Subagent 拥有独立 Run/Context/预算，以结构化结果回传。
- MCP Client 完成连接、发现、动态注册和本地权限代理。
- Team 支持 Lead/Worker、Task Board、Mailbox、request-response 协议。
- 引入 lease、幂等消息、Agent 生命周期和有限并发。
- 文件修改任务支持 Git worktree/branch 绑定与安全清理协议。

### 关键验收

1. 父 Agent 未显式传递的消息、Memory 和 Secret 不出现在子 Agent Prompt。
2. MCP 工具上线/下线不会破坏运行中的 Tool Catalog Snapshot。
3. 外部 MCP 工具仍经过本地 Permission/Audit/Timeout。
4. 两个 Worker 不能同时 claim 同一 Task。
5. Agent 崩溃、消息重复投递、lease 超时均可恢复且不重复已确认副作用。
6. Task complete 不自动删除 worktree，未提交改动受到保护。

## Phase 4：Eval 与 Serving

范围：Eval、Serving。

### 目标

- 建立版本化 Eval Dataset、Runner、确定性 Grader 和对比报告。
- 支持基于历史 Trace 的无副作用 replay。
- 将 RuntimeFacade 暴露为 Session API；CLI 继续作为一个 Client。
- 增加 Agent Worker、持久队列、任务调度、认证、租户隔离和服务监控。
- SQLite/本地 Artifact 可替换为生产数据库/对象存储。
- 提供容器化部署、健康检查、限流、配额、备份和运维手册。

### 关键验收

1. 同一 Eval Dataset 可比较不同 Prompt、模型和 Runtime 版本的成功率、成本与延迟。
2. Replay 默认不能触发真实副作用。
3. API 重试不会创建重复 Run 或 Tool Call。
4. 多租户数据、Memory、Tool 权限和 Artifact 均隔离。
5. Worker 崩溃后任务可恢复，队列至少一次投递不导致重复副作用。
6. 服务指标、Trace 和 Audit 可关联，且 Secret 不出现在 Log/Trace。

## 12.5 跨阶段工程门禁

每个阶段完成前必须满足：

- 协议/Schema 版本化并有兼容性测试；
- 核心状态机与 Permission 单元测试；
- 端到端 happy path、拒绝路径、超时和恢复路径测试；
- 日志脱敏与工作区越界安全测试；
- 关键架构取舍写入 ADR；
- 数据迁移和回滚/备份说明；
- 更新 README、TDD 和 HANDOFF；
- 验收结果可由命令或 Eval 报告复现。

## 12.6 建议的首个教学式迭代

Phase 1 继续拆成四个可独立检查的小步：

1. **协议与状态骨架**：定义内部 Message、Session/Run/Step 状态机及内存 Fake Repository，用测试验证合法转换。
2. **最小 Agent Loop**：接入 Fake Model，只实现文本结束和一个 Fake Tool 闭环。
3. **Tool 与 Permission 管线**：加入 Registry、Schema 校验、allow/deny/approval 和审计事件。
4. **真实适配器与持久化**：接入 Anthropic、PowerShell/文件工具和 SQLite，再验证 CLI 重启恢复。

这个顺序先固定最难变更的协议和边界，再接入外部 SDK 与真实副作用，能够让每一步都小、可理解、可测试。

---

## 附录 A：核心不变量

1. 未通过 Schema 与 Permission 的 ToolCall 永远不能到达 Handler。
2. 任何 ToolCall 都必须得到一个终态或等待态 ToolResult，拒绝也必须回填。
3. 非幂等副作用的不确定结果永远不能自动假设失败并重试。
4. Checkpoint 创建后不可原地修改；恢复必须校验版本与 hash。
5. Agent 只能读取其身份与 scope 允许的 Context、Memory、Artifact 和 Tool。
6. 最终完成必须引用验收结果，不能只依赖模型自述。
7. Log 不是状态真相来源；Trace 不是 Audit 的替代；Eval 不能默认执行真实副作用。
8. 动态工具变化通过版本化 Catalog Snapshot 生效，不修改正在执行的请求。
9. 高风险动作的 Audit intent 未持久化时必须拒绝执行。
10. 核心 Runtime 不依赖 CLI、具体 Provider、具体数据库或具体 MCP SDK。

## 附录 B：主要风险与缓解

| 风险 | 缓解 |
|---|---|
| 模型生成危险或错误参数 | Schema、规范化、Permission、审批、工作区/网络硬边界 |
| 崩溃导致重复副作用 | pre-side-effect checkpoint、幂等键、结果协调、unknown 状态 |
| 长上下文丢失关键约束 | 必须项保护、结构化 Summary、provenance、完整 Transcript |
| 长期记忆污染或泄漏 | Candidate 审核策略、scope/ACL、敏感过滤、来源与有效期 |
| MCP Server 不可信 | 命名空间、本地权限代理、Schema 校验、超时、隔离、结果脱敏 |
| 多 Agent 重复工作/文件冲突 | 事务 claim、lease、Mailbox 去重、worktree 绑定 |
| Trace/Log 泄露 Secret | 统一 Redaction、敏感字段声明、Artifact ACL、保存分级 |
| Provider 行为差异破坏 Loop | 内部统一协议、Provider 契约测试、归一化错误 |
| 架构过早复杂化 | 按 Phase 交付；端口先行，未使用能力不提前实现 |
| Eval 被模型评分误导 | 确定性验证优先、人工证据、多指标与版本化 rubric |
