"""工具实现与执行边界之间的稳定端口。"""

from abc import ABC, abstractmethod
from typing import Mapping

from .schema import ToolDefinition


class Tool(ABC):
    """可注册工具的最小端口，避免执行器绑定具体实现。"""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """返回可安全暴露给模型和运行时的工具定义。"""

    @abstractmethod
    def run(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        """执行工具并返回仅含 JSON 原生值的对象结果。"""
