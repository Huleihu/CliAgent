"""根据子 Agent 策略构造受限工具目录。"""

from local_dev_agent.tools import ToolRegistry

from .policy import SubagentPolicy


class SubagentToolRegistryFactory:
    """从父工具目录选择允许能力，为每个子 Agent 创建独立注册表。"""

    def __init__(self, parent_registry: ToolRegistry, policy: SubagentPolicy) -> None:
        if not isinstance(parent_registry, ToolRegistry):
            raise TypeError("父工具目录必须是 ToolRegistry 对象。")
        if not isinstance(policy, SubagentPolicy):
            raise TypeError("子 Agent 策略必须是 SubagentPolicy 对象。")
        self._parent_registry = parent_registry
        self._policy = policy

    def create(self) -> ToolRegistry:
        """按白名单创建新目录；工具实例共享受控工作区能力而非消息上下文。"""

        registry = ToolRegistry()
        for tool_name in self._policy.allowed_tool_names:
            registry.register(self._parent_registry.get(tool_name))
        return registry

    @property
    def policy(self) -> SubagentPolicy:
        """返回构造子目录时使用的不可变策略快照。"""

        return self._policy
