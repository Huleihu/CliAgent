# Agent Harness：20 章学习总览

> 目标：构建的不是“替模型思考的流程图”，而是一个让模型能够安全感知、行动、协作和恢复的 Harness。

## 一条不变的主线

所有机制最终都服务于同一个循环：

```text
用户 / 运行时事件
→ messages
→ LLM
→ tool_use？
  ├─ 否：返回文本或进入空闲
  └─ 是：Harness 执行工具
          → tool_result 写回 messages
          → 回到 LLM
```

模型决定“做什么”；Harness 决定“能做什么、如何执行、结果如何回来、状态如何保存”。

## 20 章地图

| 章节 | 解决的真实问题 | 新增机制 | 在 Agent Loop 中的位置 |
|---|---|---|---|
| S01 Agent Loop | 模型如何行动 | 模型调用 + Bash + `tool_result` | 循环本体 |
| S02 Tool Use | 如何增加能力而不重写循环 | 工具 schema + handler dispatch | `tool_use → handler` |
| S03 Permission | 模型可能请求危险操作 | allow / deny / approval | 工具执行前 |
| S04 Hooks | 权限、日志等不应污染每个工具 | 生命周期 Hook | Loop 与工具之间 |
| S05 TodoWrite | 长任务容易偏离目标 | 会话内执行计划 | 作为可调用工具回填模型 |
| S06 Subagent | 主上下文不应塞进所有边角工作 | 独立子循环 + 摘要返回 | 主工具调用分支 |
| S07 Skill Loading | 全部知识常驻会浪费上下文 | 技能目录 + 按需加载 | system / tool_result 上下文 |
| S08 Context Compact | `messages` 会超过模型上下文 | 分层压缩与摘要 | 每次模型调用前、错误后 |
| S09 Memory | 跨会话不能只靠聊天历史 | 选择、提取、索引、持久记忆 | 运行前注入 / 运行后沉淀 |
| S10 System Prompt | Prompt 不应是一段固定字符串 | 按运行状态组装 section | 每轮模型调用前 |
| S11 Error Recovery | 网络、限额、上下文错误会中断任务 | 分类恢复、重试、降级 | 模型调用异常分支 |
| S12 Task System | 大目标需跨会话持续推进 | 持久任务 DAG | 工具与磁盘状态 |
| S13 Background Tasks | 慢工具会阻塞 Agent | 后台执行 + 完成通知 | 工具分流 / 后续回合注入 |
| S14 Cron | 某些工作不应等用户触发 | 定时器 + 触发队列 | 运行时事件注入 |
| S15 Agent Teams | 单 Agent 无法高效处理大任务 | Lead、队友、独立上下文、邮箱 | 子运行时与异步消息 |
| S16 Team Protocols | 普通文本不足以处理审批、关机 | request-response + `request_id` 状态机 | 收件箱路由 |
| S17 Autonomous Agents | Lead 手动派工会成为瓶颈 | 任务板扫描、自主认领、IDLE | 队友 `WORK → IDLE` 外层循环 |
| S18 Worktree Isolation | 多人同目录改代码会冲突 | 任务绑定 Git worktree / branch | 工具 `cwd` 与任务状态 |
| S19 MCP | 内置工具无法覆盖所有外部系统 | 连接、发现、动态工具池 | 调用模型前组装 tools |
| S20 Comprehensive | 机制组合时容易互相破坏 | 明确的统一插入点 | 完整 Harness Loop |

## 核心机制与可迁移原则

### 1. 工具不是 Prompt，而是受控接口

工具由三部分组成：模型可见的 schema、Harness 的 handler、返回模型的 `tool_result`。

```text
模型 tool_use(name, input, id)
→ handler(**input)
→ {tool_use_id: id, content: output}
→ messages
→ 模型
```

没有 `tool_result`，模型无法知道真实执行结果。

### 2. 权限与 Hook 放在工具分发之前

不要让每个工具自己实现审批、日志、审计。统一管线应是：

```text
tool_use
→ PreToolUse：权限、参数 / 路径校验
→ handler：实际执行
→ PostToolUse：日志、输出检查、指标
→ tool_result
```

拒绝也是结果，必须回填模型，让模型能够换一种做法。

### 3. `messages` 是会话状态，不是永久记忆

`messages` 保存当前推理所需的用户输入、模型输出和工具往返；它会增长，必须压缩。

```text
优先：截断超大工具输出
→ 删除或替换旧工具结果
→ 保留首尾关键回合
→ 摘要旧历史
→ 保存 transcript 以供审计
```

持久记忆应单独保存，并在下一次运行时按需选择、注入；不要把全部历史永久塞进 Prompt。

### 4. 任务状态比 Todo 更适合跨会话工作

`TodoWrite` 只管理当前会话焦点。真正的任务系统需要持久状态与依赖：

```text
pending
→ claim
→ in_progress
→ complete
→ completed
```

任务文件至少需要：`id`、`subject`、`description`、`owner`、`status`、`blockedBy`。生产中，claim 必须使用锁或事务，保证“检查可领 + 写入 owner”原子执行。

### 5. 异步任务有两类结果

后台任务启动时的 `tool_result` 只表示“已受理”；真正完成结果是新的运行时通知。

```text
模型调用慢工具
→ 立即回填：background started
→ 后台执行
→ 完成后产生 notification
→ 下一轮作为新用户侧内容注入模型
```

不要把后台完成结果伪装成原来的 `tool_use_id` 的同步结果。

### 6. 团队协作依赖边界清晰的状态与消息

每个队友拥有独立 `messages`，不能共享主 Agent 的对话上下文。协作通过：

```text
共享：任务板、协议状态、受控工作区
异步传递：mailbox 消息
独立拥有：每个 Agent 的推理上下文
```

需要确认的动作使用结构化协议：

```text
request_id
→ pending
→ response
→ approved / rejected
```

`approved` / `rejected` 表示谁拥有该决策权：计划通常由 Lead 审批；关机通常由被请求的队友确认。

### 7. 自主团队不是“没有 Lead”

Lead 负责目标、任务、例外和成果验收；队友负责在空闲时自己扫描任务板、领取可执行任务。

```text
Lead：create_task / 建立依赖 / 准备环境 / 处理例外
Worker：IDLE → scan → claim → WORK → complete → IDLE
```

依赖已经满足、任务正常完成等可由确定性规则推进；方案选择、权限审批、长期失败等才需要唤醒 Lead 或人工。

### 8. 任务归属与文件系统归属是两件事

S17 的 `owner` 解决“谁负责”；S18 的 worktree 解决“在哪改”。

```text
task_auth
  owner = alice
  worktree = auth

→ .worktrees/auth/
→ branch wt/auth
```

完成任务不代表可以删除 worktree。必须先审查、合并或明确丢弃；清理前应检查未提交改动和未推送提交。

### 9. MCP 是外部能力的统一接入协议

MCP 不是模型工具本身，而是 Host 与外部 Server 发现和调用能力的协议。

```text
connect MCP Server
→ initialize / 能力协商
→ tools/list
→ Harness 规范化并合并工具池
→ 模型调用 mcp__server__tool
→ Host 转发 tools/call
→ tool_result 回到模型
```

MCP Server 提供工具；Harness 仍必须负责名称隔离、权限、认证、超时、重试、结果处理和审计。

### 10. 状态要区分运行态与持久态

| 状态 | 适合位置 | 进程重启后 |
|---|---|---|
| `messages`、重试计数、MCP 连接、后台线程 | 内存 | 丢失，需要 checkpoint / 重建 |
| 任务、依赖、owner | 数据库或任务文件 | 保留 |
| worktree 与 Git 改动 | 文件系统与 Git | 保留 |
| 审批请求、后台 job、队友心跳 | 持久状态库 / 队列 | 生产中必须保留 |
| 收件箱与事件 | durable queue / event log | 应可重放或幂等处理 |

教学代码演示了部分持久化；生产 Runtime 还需要 checkpoint、持久队列、恢复扫描、幂等性和超时处理。

## 构建自己的 Agent：推荐顺序

不要一次复制 20 种机制。先为一个真实产品需求选最小集合。

```text
阶段 1：可靠单 Agent
1. Agent Loop + 工具 schema / dispatch
2. 权限与路径边界
3. tool_result、日志、基础错误处理

阶段 2：可持续工作
4. 会话上下文预算与压缩
5. 持久任务系统
6. 记忆与运行状态 checkpoint
7. 后台 job / runtime event queue

阶段 3：扩展能力与协作
8. MCP（先只读、最小权限）
9. 子 Agent 或团队
10. 任务锁、worktree、审批协议

阶段 4：生产化
11. durable queue、事件重放、幂等
12. 认证、审计、可观测性、限流、监控
```

## 实作时始终追踪的六个问题

对任何新机制，都按这条链检查：

```text
一个具体输入
→ 哪个函数被调用
→ 哪个状态被修改
→ 数据 / 消息写到哪里
→ 哪个循环或消费者读取它
→ 什么时候、以什么形式回到模型
```

若其中任意一环不清楚，机制通常还没有真正设计完整。

## 结束语

好的 Agent 产品不是堆叠 Prompt，也不是用规则替模型做决定。

```text
Model：理解、选择、推理
Harness：工具、上下文、状态、权限、事件、隔离、恢复
```

先把 Harness 的边界和数据流做清楚，再让模型在这个可控环境中发挥能力。
