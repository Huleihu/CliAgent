"""将一次长期记忆加载结果转换为派生模型请求视图。"""

from __future__ import annotations

from dataclasses import dataclass

from local_dev_agent.context import ContextInputSnapshot
from local_dev_agent.models import MessageRole, ModelMessage, TextBlock

from .loading import MemoryLoadResult


MEMORY_CATALOG_SYSTEM_PROMPT = """以下是当前工作区可用的长期记忆目录。

相关记忆的完整正文会按需附在当前用户请求中。应遵守其中仍与当前任务相关的用户偏好、反馈和项目事实。"""


@dataclass(frozen=True, slots=True)
class MemoryRequestContext:
    """一次 Run 固定的长期记忆派生视图，不拥有或改写原始消息。"""

    load_result: MemoryLoadResult

    def __post_init__(self) -> None:
        """保持加载快照不可变，确保同一 Run 的重试使用相同选择结果。"""

        if not isinstance(self.load_result, MemoryLoadResult):
            raise ValueError("字段“load_result”必须是 MemoryLoadResult 对象。")

    def enrich(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        """在检查点视图之后注入目录和正文，绝不触碰原始 Transcript。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise TypeError("snapshot 必须是 ContextInputSnapshot 对象。")
        system_prompt = self._with_catalog_prompt(snapshot.system_prompt)
        messages = self._with_relevant_memories(snapshot.messages)
        if system_prompt == snapshot.system_prompt and messages == snapshot.messages:
            return snapshot
        return ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=messages,
            tools=snapshot.tools,
            system_prompt=system_prompt,
        )

    def _with_catalog_prompt(self, system_prompt: str | None) -> str | None:
        if not self.load_result.catalog_text:
            return system_prompt
        memory_prompt = (
            f"{MEMORY_CATALOG_SYSTEM_PROMPT}\n\n{self.load_result.catalog_text.rstrip()}"
        )
        return "\n\n".join(
            prompt for prompt in (system_prompt, memory_prompt) if prompt
        )

    def _with_relevant_memories(
        self,
        messages: tuple[ModelMessage, ...],
    ) -> tuple[ModelMessage, ...]:
        if not self.load_result.relevant_memories_text:
            return messages
        for message_index in range(len(messages) - 1, -1, -1):
            message = messages[message_index]
            if message.role is not MessageRole.USER:
                continue
            for block_index, block in enumerate(message.content):
                if not isinstance(block, TextBlock):
                    continue
                replacement = ModelMessage(
                    role=MessageRole.USER,
                    content=(
                        *message.content[:block_index],
                        TextBlock(
                            f"{self.load_result.relevant_memories_text}\n\n{block.text}"
                        ),
                        *message.content[block_index + 1 :],
                    ),
                )
                return (
                    *messages[:message_index],
                    replacement,
                    *messages[message_index + 1 :],
                )
        return messages
