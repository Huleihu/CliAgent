"""运行结束后从完整原始消息提取长期记忆。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from local_dev_agent.models import (
    MessageRole,
    ModelClient,
    ModelMessage,
    ModelRequest,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from .ports import MemoryRepository
from .schema import MemoryCatalog, MemoryEntry, MemoryType


MEMORY_EXTRACTION_SYSTEM_PROMPT = """从当前已结束的 Agent 对话中提取可跨会话复用的新长期记忆。

只提取明确的用户偏好、反馈、稳定项目事实或外部参考线索。只输出 JSON 数组；每项必须包含 name、type、description、content。type 只能是 user、feedback、project、reference。没有新信息时输出 []。不要调用工具。"""


@dataclass(frozen=True, slots=True)
class MemoryExtractionRequest:
    """一次运行结束后供提取器使用的完整原始消息和目录快照。"""

    session_id: str
    run_id: str
    messages: tuple[ModelMessage, ...]
    catalog: MemoryCatalog

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("字段“session_id”必须是非空字符串。")
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError("字段“run_id”必须是非空字符串。")
        if not isinstance(self.messages, tuple) or not self.messages:
            raise ValueError("字段“messages”必须是非空 ModelMessage 元组。")
        if not all(isinstance(message, ModelMessage) for message in self.messages):
            raise ValueError("字段“messages”必须是非空 ModelMessage 元组。")
        if not isinstance(self.catalog, MemoryCatalog):
            raise ValueError("字段“catalog”必须是 MemoryCatalog 对象。")


class MemoryExtractor(Protocol):
    """从原始对话提出候选记忆，不直接接触文件系统。"""

    def extract(self, request: MemoryExtractionRequest) -> tuple[MemoryEntry, ...]:
        """返回已验证的候选条目；实现方不得调用工具。"""


class ModelMemoryExtractor:
    """复用无工具模型调用提取候选记忆。"""

    def __init__(self, model: ModelClient) -> None:
        if not hasattr(model, "generate"):
            raise ValueError("model 必须提供 generate 方法。")
        self._model = model

    def extract(self, request: MemoryExtractionRequest) -> tuple[MemoryEntry, ...]:
        if not isinstance(request, MemoryExtractionRequest):
            raise TypeError("request 必须是 MemoryExtractionRequest 对象。")
        response = self._model.generate(
            ModelRequest.from_messages(
                session_id=request.session_id,
                run_id=request.run_id,
                messages=(
                    ModelMessage(
                        role=MessageRole.USER,
                        content=(TextBlock(self._format_prompt(request)),),
                    ),
                ),
                system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
            )
        )
        if response.stop_reason is not StopReason.END_TURN:
            raise ValueError("记忆提取模型未正常结束。")
        payload = json.loads(response.text.strip())
        if not isinstance(payload, list):
            raise ValueError("记忆提取模型未返回数组。")
        entries: list[MemoryEntry] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                entry = MemoryEntry(
                    memory_id=item.get("name"),
                    memory_type=MemoryType(item.get("type")),
                    description=item.get("description"),
                    content=item.get("content"),
                )
            except (TypeError, ValueError):
                continue
            if entry.memory_id not in {value.memory_id for value in entries}:
                entries.append(entry)
        return tuple(entries)

    @staticmethod
    def _format_prompt(request: MemoryExtractionRequest) -> str:
        existing = "\n".join(
            f"- {entry.memory_id}: {entry.description}"
            for entry in request.catalog.entries
        ) or "（无）"
        messages = json.dumps(
            [_message_to_json(message) for message in request.messages],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"已有记忆：\n{existing}\n\n当前运行原始消息：\n{messages}"


class MemoryExtractionService:
    """协调目录去重、候选提取和原子记忆保存。"""

    def __init__(self, repository: MemoryRepository, extractor: MemoryExtractor) -> None:
        if not hasattr(repository, "list_entries") or not hasattr(repository, "save"):
            raise ValueError("repository 必须提供 list_entries 和 save 方法。")
        if not hasattr(extractor, "extract"):
            raise ValueError("extractor 必须提供 extract 方法。")
        self._repository = repository
        self._extractor = extractor

    def extract_and_save(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: tuple[ModelMessage, ...],
    ) -> tuple[MemoryEntry, ...]:
        catalog = self._repository.list_entries()
        candidates = self._extractor.extract(
            MemoryExtractionRequest(session_id, run_id, messages, catalog)
        )
        existing_ids = {entry.memory_id for entry in catalog.entries}
        saved: list[MemoryEntry] = []
        for entry in candidates:
            if entry.memory_id in existing_ids:
                continue
            self._repository.save(entry)
            existing_ids.add(entry.memory_id)
            saved.append(entry)
        return tuple(saved)


def _message_to_json(message: ModelMessage) -> dict[str, object]:
    content: list[dict[str, object]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            content.append({"type": "tool_use", "name": block.name, "input": dict(block.input)})
        elif isinstance(block, ToolResultBlock):
            content.append({"type": "tool_result", "content": dict(block.content), "is_error": block.is_error})
    return {"role": message.role.value, "content": content}
