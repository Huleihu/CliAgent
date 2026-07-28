"""长期记忆的可替换选择策略与模型降级适配器。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Protocol

from local_dev_agent.models import (
    MessageRole,
    ModelClient,
    ModelMessage,
    ModelRequest,
    StopReason,
    TextBlock,
)

from .schema import MemoryCatalog


MEMORY_SELECTION_SYSTEM_PROMPT = """你负责从长期记忆目录中选择与当前请求直接相关的条目。

只能输出 JSON 字符串数组，数组元素必须是目录中的 memory_id。最多选择指定数量；不确定时返回空数组。不要调用工具，不要解释。"""


def _require_nonempty_text(field_name: str, value: str) -> str:
    """验证模型关联标识与查询文本，避免产生无法审计的选择请求。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


@dataclass(frozen=True, slots=True)
class MemorySelectionRequest:
    """一次记忆选择所需的关联信息、查询和不可变目录快照。"""

    session_id: str
    run_id: str
    query: str
    catalog: MemoryCatalog
    max_items: int = 5

    def __post_init__(self) -> None:
        """在调用选择器前固定输入，避免目录或预算在选择期间漂移。"""

        object.__setattr__(self, "session_id", _require_nonempty_text("session_id", self.session_id))
        object.__setattr__(self, "run_id", _require_nonempty_text("run_id", self.run_id))
        object.__setattr__(self, "query", _require_nonempty_text("query", self.query))
        if not isinstance(self.catalog, MemoryCatalog):
            raise ValueError("字段“catalog”必须是 MemoryCatalog 对象。")
        if (
            isinstance(self.max_items, bool)
            or not isinstance(self.max_items, int)
            or self.max_items < 1
        ):
            raise ValueError("字段“max_items”必须是正整数。")


class MemorySelector(Protocol):
    """仅从目录元数据选择记忆标识，不读取文件路径或修改记忆。"""

    def select(self, request: MemorySelectionRequest) -> tuple[str, ...]:
        """返回去重后的精确 memory_id，顺序代表加载优先级。"""


class KeywordMemorySelector:
    """基于名称和描述的确定性降级选择器。"""

    def select(self, request: MemorySelectionRequest) -> tuple[str, ...]:
        """按匹配词数量降序、目录顺序升序选择，确保结果可复现。"""

        if not isinstance(request, MemorySelectionRequest):
            raise TypeError("request 必须是 MemorySelectionRequest 对象。")
        query_terms = self._terms(request.query)
        if not query_terms:
            return ()
        scored_entries = []
        for index, entry in enumerate(request.catalog.entries):
            candidate_terms = set(self._terms(f"{entry.memory_id} {entry.description}"))
            score = len(query_terms & candidate_terms)
            if score:
                scored_entries.append((score, index, entry.memory_id))
        return tuple(
            memory_id
            for _, _, memory_id in sorted(
                scored_entries,
                key=lambda item: (-item[0], item[1]),
            )[: request.max_items]
        )

    @staticmethod
    def _terms(value: str) -> set[str]:
        """同时提取英文单词和相邻中文双字，降低单字误匹配。"""

        normalized = value.lower()
        ascii_terms = set(re.findall(r"[a-z0-9]{3,}", normalized))
        chinese_sequences = re.findall(r"[\u4e00-\u9fff]+", normalized)
        chinese_terms = {
            sequence[index : index + 2]
            for sequence in chinese_sequences
            for index in range(max(0, len(sequence) - 1))
        }
        return ascii_terms | chinese_terms


class ModelMemorySelector:
    """用无工具模型请求选择记忆，并在任何异常时退回确定性策略。"""

    def __init__(
        self,
        model: ModelClient,
        *,
        fallback: MemorySelector | None = None,
    ) -> None:
        if not hasattr(model, "generate"):
            raise ValueError("model 必须提供 generate 方法。")
        if fallback is not None and not hasattr(fallback, "select"):
            raise ValueError("fallback 必须提供 select 方法。")
        self._model = model
        self._fallback = fallback or KeywordMemorySelector()

    def select(self, request: MemorySelectionRequest) -> tuple[str, ...]:
        """解析严格 JSON 数组；模型响应不可信时不阻断主任务。"""

        if not isinstance(request, MemorySelectionRequest):
            raise TypeError("request 必须是 MemorySelectionRequest 对象。")
        if not request.catalog.entries:
            return ()
        try:
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
                    system_prompt=MEMORY_SELECTION_SYSTEM_PROMPT,
                )
            )
            if response.stop_reason is not StopReason.END_TURN:
                raise ValueError("记忆选择模型未正常结束。")
            return self._validate_selected_ids(request, json.loads(response.text.strip()))
        except Exception:
            return self._fallback.select(request)

    @staticmethod
    def _format_prompt(request: MemorySelectionRequest) -> str:
        catalog = "\n".join(
            f"- {entry.memory_id}: {entry.description}"
            for entry in request.catalog.entries
        )
        return (
            f"当前请求：\n{request.query}\n\n"
            f"最多选择 {request.max_items} 条。\n\n"
            f"长期记忆目录：\n{catalog}"
        )

    @staticmethod
    def _validate_selected_ids(
        request: MemorySelectionRequest,
        selected_ids: object,
    ) -> tuple[str, ...]:
        if not isinstance(selected_ids, list) or not all(
            isinstance(memory_id, str) for memory_id in selected_ids
        ):
            raise ValueError("记忆选择模型未返回字符串数组。")
        available_ids = {entry.memory_id for entry in request.catalog.entries}
        result: list[str] = []
        for memory_id in selected_ids:
            if memory_id not in available_ids or memory_id in result:
                continue
            result.append(memory_id)
            if len(result) == request.max_items:
                break
        return tuple(result)
