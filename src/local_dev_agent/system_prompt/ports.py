"""运行时取得系统提示的可替换端口。"""

from typing import Protocol


class SystemPromptProvider(Protocol):
    """按当前运行时状态返回派生系统提示，不持久化任何消息。"""

    def get_system_prompt(self) -> str | None:
        """返回当前模型请求应使用的系统提示；无内容时返回 None。"""
