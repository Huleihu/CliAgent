"""长期记忆的低频整理、合并与去重。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from local_dev_agent.models import MessageRole, ModelClient, ModelMessage, ModelRequest, StopReason, TextBlock

from .ports import MemoryRepository
from .schema import MemoryCatalog, MemoryEntry, MemoryType


MEMORY_CONSOLIDATION_SYSTEM_PROMPT = """整理长期记忆：合并重复项，删除过时或冲突项，优先保留明确用户偏好。

只输出 JSON 数组；每项必须包含 name、type、description、content。不要调用工具。"""


@dataclass(frozen=True, slots=True)
class MemoryConsolidationPolicy:
    """用明确数量阈值控制同步整理频率。"""

    entry_threshold: int = 10

    def __post_init__(self) -> None:
        if isinstance(self.entry_threshold, bool) or not isinstance(self.entry_threshold, int) or self.entry_threshold < 1:
            raise ValueError("字段“entry_threshold”必须是正整数。")

    def should_consolidate(self, catalog: MemoryCatalog) -> bool:
        return len(catalog.entries) >= self.entry_threshold


class MemoryConsolidator(Protocol):
    def consolidate(self, catalog: MemoryCatalog, *, session_id: str, run_id: str) -> MemoryCatalog:
        """返回完整、稳定排序的新目录。"""


class ModelMemoryConsolidator:
    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def consolidate(self, catalog: MemoryCatalog, *, session_id: str, run_id: str) -> MemoryCatalog:
        response = self._model.generate(ModelRequest.from_messages(session_id=session_id, run_id=run_id, messages=(ModelMessage(MessageRole.USER, (TextBlock(self._prompt(catalog)),)),), system_prompt=MEMORY_CONSOLIDATION_SYSTEM_PROMPT))
        if response.stop_reason is not StopReason.END_TURN:
            raise ValueError("记忆整理模型未正常结束。")
        payload = json.loads(response.text.strip())
        if not isinstance(payload, list):
            raise ValueError("记忆整理模型未返回数组。")
        entries = [MemoryEntry(item.get("name"), MemoryType(item.get("type")), item.get("description"), item.get("content")) for item in payload if isinstance(item, dict)]
        if len(entries) != len(payload):
            raise ValueError("记忆整理模型返回了非法条目。")
        return MemoryCatalog(entries=tuple(sorted(entries, key=lambda entry: entry.memory_id)))

    @staticmethod
    def _prompt(catalog: MemoryCatalog) -> str:
        return json.dumps([{"name": entry.memory_id, "type": entry.memory_type.value, "description": entry.description, "content": entry.content} for entry in catalog.entries], ensure_ascii=False, separators=(",", ":"))


class MemoryConsolidationService:
    def __init__(self, repository: MemoryRepository, consolidator: MemoryConsolidator, policy: MemoryConsolidationPolicy | None = None) -> None:
        self._repository = repository
        self._consolidator = consolidator
        self._policy = policy or MemoryConsolidationPolicy()

    def consolidate_if_needed(self, *, session_id: str, run_id: str) -> bool:
        catalog = self._repository.list_entries()
        if not self._policy.should_consolidate(catalog):
            return False
        self._repository.replace_all(self._consolidator.consolidate(catalog, session_id=session_id, run_id=run_id))
        return True
