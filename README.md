# local-dev-agent

一个受 Claude Code 启发、在本地运行的开发 Agent 学习项目。当前先搭建可靠的开发环境与 Harness 基础，再按实际需求逐步实现能力。

## 开发环境

项目使用 Conda 环境 `local-dev-agent`，Python 3.13。

首次创建环境：

```powershell
conda env create -f environment.yml
```

已存在环境时更新依赖：

```powershell
conda env update -f environment.yml --prune
```

激活环境：

```powershell
conda activate local-dev-agent
```

## 本地配置

复制 `.env.example` 为 `.env`，再填写实际的模型访问配置。`.env` 不会被提交到 Git。

```powershell
Copy-Item .env.example .env
```

当前真实模型使用 DeepSeek 的 Anthropic 兼容接口。请在 `.env` 中填写
`DEEPSEEK_API_KEY`；模型名、接口地址和最大输出 Token 可按需要调整。当前
Runtime 为了安全地完成工具结果回填，显式关闭 DeepSeek thinking 模式；推理内容
不会进入本地状态、日志或后续模型请求。

可选设置 `DEEPSEEK_FALLBACK_MODEL`。当同一父 Agent Run 连续遭遇 3 次 HTTP 529
服务过载时，Runtime 会在有界退避后改用该备用模型继续重试；未设置时仍使用主模型。
运行入口创建模型客户端时，先加载 `.env`，再读取配置：

```python
from dotenv import load_dotenv

from local_dev_agent.models import DeepSeekAnthropicModelClient, DeepSeekSettings

load_dotenv()
model = DeepSeekAnthropicModelClient(DeepSeekSettings.from_environment())
```

## 运行最小交互式 Demo

填写 `.env` 后，在项目根目录运行：

```powershell
python -m local_dev_agent
```

程序会创建一个本地 Session，并对每条终端输入创建一个 Run。默认工作区固定为
项目根目录下的 `sandbox/`，输入 `q`、`exit` 或空行可退出；运行状态和日志分别
保存在 `sandbox/var/state/`、`sandbox/var/logs/`。
当前父 Agent 默认提供受工作区与权限边界保护的文件读写、待办清单、持久任务图、
上下文压缩、受控委派和 shell 命令等能力；技能目录存在时还会提供按需加载能力。
子 Agent 仍只继承四项工作区文件工具，不会获得命令执行、后台任务、待办或任务图
能力。

shell 命令的工作目录固定为 `sandbox/`，并完整经过参数校验、权限和 Hook 链。短命令
默认前台返回结果；显式选择后台执行或命中保守的慢命令策略时，工具立即返回 `bg_id`，
父 Agent 可继续调用其他工具，完成或失败通知会在后续模型请求中按当前 Session 一次性
送达。后台任务首版只保存在当前进程内并由 daemon 线程执行，退出 CLI 后不会恢复仍在
运行的任务。

父 Agent 还可创建、查看和取消五段式 cron 定时任务。调度线程只根据本地时区判断
到期并写入内存 Trigger 队列；独立的队列处理线程在共享 Agent 执行租约空闲时，才为
该 Trigger 启动新的 Run。支持 `*`、`*/N`、`N`、`N-M` 与 `N,M,...`；日和星期同时
受限时采用 cron 标准 OR 语义。一次性任务成功入队后立即移除，同一任务同一 UTC 分钟
不会重复触发。session-only 定义仅在当前进程和创建 Session 中存在；durable 定义保存到
`sandbox/var/state/cron/scheduled_tasks.json` 并在下次 CLI 启动时恢复，但应用关闭期间
不会触发。Cron 仅注册给父 Agent，子 Agent 仍只拥有四项文件工具。

同一进程内的后续输入会复用该 Session 已持久化的用户消息、工具调用、工具结果与助手
文本，因此“读取它的前 20 行”能够引用上一轮已发现的文件。消息历史保存在
`sandbox/var/state/conversations/`。

## 常用命令

```powershell
# 检查已安装依赖是否存在冲突
python -m pip check

# 静态检查（开始实现代码后使用）
ruff check .

# 运行测试（开始添加测试后使用）
pytest
```

## 项目资料

- `learnClaude/`：Agent Harness 的分阶段学习资料与示例。
- `AGENTS.md`：项目开发与提交规则。
- `HANDOFF.md`：当前状态、变更记录、验证结果与下一步。
