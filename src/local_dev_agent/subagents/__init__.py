"""子 Agent 的委派契约与可替换运行端口。"""

from .ports import SubagentRunner
from .schema import SubagentOutcome, SubagentResult, SubagentTask

__all__ = [
    "SubagentOutcome",
    "SubagentResult",
    "SubagentRunner",
    "SubagentTask",
]
