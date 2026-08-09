"""工具实现与执行边界之间的稳定端口。"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping, Protocol

from .schema import ToolDefinition, ToolExecutionContext


class ToolWorkingDirectoryResolver(Protocol):
    """按一次工具调用所属 Run 返回其受限工作目录。"""

    def resolve(self, *, context: ToolExecutionContext | None) -> Path:
        """未绑定 Run 时返回主工作区，已绑定 Run 时返回其专属目录。"""


class RunWorkingDirectoryRegistry(ToolWorkingDirectoryResolver, Protocol):
    """维护短生命周期的 Run 到工作目录映射，避免改变进程全局 cwd。"""

    def bind(self, *, run_id: str, directory: Path) -> None:
        """在 Agent Loop 执行前登记该 Run 的工作目录。"""

    def release(self, *, run_id: str) -> None:
        """在 Agent Loop 结束后移除映射，防止后续 Run 误用目录。"""


class Tool(ABC):
    """可注册工具的最小端口，避免执行器绑定具体实现。"""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """返回可安全暴露给模型和运行时的工具定义。"""

    @abstractmethod
    def run(
        self,
        arguments: Mapping[str, object],
        *,
        context: ToolExecutionContext | None = None,
    ) -> Mapping[str, object]:
        """在可选关联上下文中执行工具，并返回仅含 JSON 原生值的对象结果。"""
