"""按生命周期事件隔离管理 Hook 注册信息。"""

from .errors import HookAlreadyExistsError, HookValidationError
from .ports import Hook
from .schema import HookEvent


class HookRegistry:
    """维护每个事件的有序 Hook 集合，不负责实际调用。"""

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[Hook]] = {
            event: [] for event in HookEvent
        }

    def register(self, event: HookEvent, hook: Hook) -> None:
        """为事件注册一个命名 Hook，拒绝同事件内的重名覆盖。"""

        self._validate_event(event)
        if not isinstance(hook, Hook):
            raise TypeError("只能注册 Hook 类型的对象。")
        if not isinstance(hook.name, str) or not hook.name.strip():
            raise HookValidationError("Hook 名称必须是非空字符串。")
        if any(existing_hook.name == hook.name for existing_hook in self._hooks[event]):
            raise HookAlreadyExistsError(event=event.value, hook_name=hook.name)
        self._hooks[event].append(hook)

    def list_hooks(self, event: HookEvent) -> tuple[Hook, ...]:
        """按注册顺序返回某个事件的 Hook 快照。"""

        self._validate_event(event)
        return tuple(self._hooks[event])

    def registered_events(self) -> tuple[HookEvent, ...]:
        """返回含有至少一个 Hook 的事件，供诊断和装配检查使用。"""

        return tuple(event for event, hooks in self._hooks.items() if hooks)

    @staticmethod
    def _validate_event(event: HookEvent) -> None:
        if not isinstance(event, HookEvent):
            raise HookValidationError("事件必须是 HookEvent 枚举值。")
