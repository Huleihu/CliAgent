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
`DEEPSEEK_API_KEY`；模型名、接口地址和最大输出 Token 可按需要调整。
运行入口创建模型客户端时，先加载 `.env`，再读取配置：

```python
from dotenv import load_dotenv

from local_dev_agent.models import DeepSeekAnthropicModelClient, DeepSeekSettings

load_dotenv()
model = DeepSeekAnthropicModelClient(DeepSeekSettings.from_environment())
```

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
