"""后台任务领域与基础设施之间的稳定端口。"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .schema import BackgroundTask, CommandExecutionResult


class BackgroundTaskIdGenerator(Protocol):
    """为后台任务生成可由不同基础设施替换的稳定标识。"""

    def new_task_id(self) -> str:
        """返回一个尚未写入仓储的新后台任务标识。"""


class BackgroundTaskRepository(Protocol):
    """保存后台任务快照，不绑定内存、文件或数据库实现。"""

    def add(self, task: BackgroundTask) -> BackgroundTask:
        """新增一个运行中的任务快照。"""

    def get(self, task_id: str) -> BackgroundTask | None:
        """按任务标识读取快照；不存在时返回 None。"""

    def list_for_session(self, session_id: str) -> Sequence[BackgroundTask]:
        """按稳定顺序读取一个 Session 归属的任务快照。"""

    def replace(self, task: BackgroundTask) -> BackgroundTask:
        """以新的完整快照替换既有任务。"""


class CommandRunner(Protocol):
    """在指定工作目录运行命令，不规定线程或进程管理方式。"""

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        """返回命令退出码与输出；执行异常交由调用方转为任务失败。"""

