"""在显式指定的工具包中受控发现工具。"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from types import ModuleType

from .errors import ToolDiscoveryError
from .ports import Tool
from .registry import ToolRegistry


class ToolDiscovery:
    """扫描指定包的直接子模块，避免递归或任意路径加载。"""

    def register_package(self, package_name: str, registry: ToolRegistry) -> tuple[str, ...]:
        """发现并注册包内公开 Tool 实例或 create_tool 工厂的结果。"""

        package = self._import_package(package_name)
        if not hasattr(package, "__path__"):
            raise ToolDiscoveryError(f"工具发现目标“{package_name}”不是 Python 包。")

        registered_names: list[str] = []
        module_names = sorted(
            module_info.name
            for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}.")
        )
        for module_name in module_names:
            module = self._import_module(module_name)
            for tool in self._discover_module_tools(module):
                registry.register(tool)
                registered_names.append(tool.definition.name)
        return tuple(registered_names)

    @staticmethod
    def _import_package(package_name: str) -> ModuleType:
        try:
            return importlib.import_module(package_name)
        except (ImportError, ValueError) as error:
            raise ToolDiscoveryError(f"无法导入工具包“{package_name}”。") from error

    @staticmethod
    def _import_module(module_name: str) -> ModuleType:
        try:
            return importlib.import_module(module_name)
        except Exception as error:
            raise ToolDiscoveryError(f"无法导入工具模块“{module_name}”。") from error

    @staticmethod
    def _discover_module_tools(module: ModuleType) -> tuple[Tool, ...]:
        tools: list[Tool] = []
        for name, value in sorted(vars(module).items()):
            if name.startswith("_"):
                continue
            if isinstance(value, Tool):
                tools.append(value)
            elif name == "create_tool" and callable(value):
                tools.append(ToolDiscovery._create_tool(module.__name__, value))
        return tuple(tools)

    @staticmethod
    def _create_tool(module_name: str, factory: Callable[[], object]) -> Tool:
        try:
            tool = factory()
        except Exception as error:
            raise ToolDiscoveryError(f"工具模块“{module_name}”的 create_tool 执行失败。") from error
        if not isinstance(tool, Tool):
            raise ToolDiscoveryError(
                f"工具模块“{module_name}”的 create_tool 必须返回 Tool 对象。"
            )
        return tool
