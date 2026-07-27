"""在派生上下文中以 Artifact 引用替换超预算的大工具结果。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from local_dev_agent.models import MessageRole, ModelMessage, ToolResultBlock

from .artifacts import ToolResultArtifact, ToolResultArtifactStore
from .budget import ContextInputSnapshot


def _require_positive_integer(field_name: str, value: int) -> int:
    """拒绝布尔值、零和负数，避免压缩策略失去明确边界。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"字段“{field_name}”必须是正整数。")
    return value


@dataclass(frozen=True, slots=True)
class ToolResultBudgetResult:
    """工具结果预算处理后的派生快照与已创建 Artifact 引用。"""

    snapshot: ContextInputSnapshot
    artifacts: tuple[ToolResultArtifact, ...]
    original_total_bytes: int
    remaining_total_bytes: int

    def __post_init__(self) -> None:
        """固定结果快照与统计值，供后续压缩管线安全复用。"""

        if not isinstance(self.snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        if not isinstance(self.artifacts, tuple) or not all(
            isinstance(artifact, ToolResultArtifact) for artifact in self.artifacts
        ):
            raise ValueError("字段“artifacts”必须是 ToolResultArtifact 元组。")
        _require_nonnegative_integer("original_total_bytes", self.original_total_bytes)
        _require_nonnegative_integer("remaining_total_bytes", self.remaining_total_bytes)
        if self.remaining_total_bytes > self.original_total_bytes:
            raise ValueError("剩余工具结果字节数不能大于原始字节数。")

    @property
    def compacted(self) -> bool:
        """返回本次是否确实创建了 Artifact 并替换了模型视图。"""

        return bool(self.artifacts)


def _require_nonnegative_integer(field_name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"字段“{field_name}”必须是非负整数。")
    return value


class ToolResultBudgetCompactor:
    """仅处理最后一条工具结果消息，优先替换最大的完整输出。"""

    def __init__(
        self,
        artifact_store: ToolResultArtifactStore,
        *,
        max_total_bytes: int = 200_000,
        minimum_artifact_bytes: int = 30_000,
        preview_max_characters: int = 2_000,
    ) -> None:
        if not hasattr(artifact_store, "persist"):
            raise ValueError("artifact_store 必须提供 persist 方法。")
        max_total_bytes = _require_positive_integer("max_total_bytes", max_total_bytes)
        minimum_artifact_bytes = _require_positive_integer(
            "minimum_artifact_bytes",
            minimum_artifact_bytes,
        )
        preview_max_characters = _require_positive_integer(
            "preview_max_characters",
            preview_max_characters,
        )
        if minimum_artifact_bytes > max_total_bytes:
            raise ValueError("minimum_artifact_bytes 不能大于 max_total_bytes。")
        self._artifact_store = artifact_store
        self._max_total_bytes = max_total_bytes
        self._minimum_artifact_bytes = minimum_artifact_bytes
        self._preview_max_characters = preview_max_characters

    def compact(self, snapshot: ContextInputSnapshot) -> ToolResultBudgetResult:
        """复制末尾工具结果消息；完整 Transcript 与原输入快照保持不变。"""

        if not isinstance(snapshot, ContextInputSnapshot):
            raise ValueError("字段“snapshot”必须是 ContextInputSnapshot 对象。")
        last_message = snapshot.messages[-1]
        blocks = tuple(
            (index, block)
            for index, block in enumerate(last_message.content)
            if isinstance(block, ToolResultBlock)
        )
        original_total_bytes = sum(
            self._content_size_bytes(block) for _, block in blocks
        )
        if last_message.role is not MessageRole.USER or (
            not blocks or original_total_bytes <= self._max_total_bytes
        ):
            return ToolResultBudgetResult(
                snapshot=snapshot,
                artifacts=(),
                original_total_bytes=original_total_bytes,
                remaining_total_bytes=original_total_bytes,
            )

        replacement_blocks = list(last_message.content)
        artifacts: list[ToolResultArtifact] = []
        remaining_total_bytes = original_total_bytes
        ranked_blocks = sorted(
            blocks,
            key=lambda item: self._content_size_bytes(item[1]),
            reverse=True,
        )
        for block_index, block in ranked_blocks:
            if remaining_total_bytes <= self._max_total_bytes:
                break
            block_size_bytes = self._content_size_bytes(block)
            if block_size_bytes < self._minimum_artifact_bytes:
                continue
            artifact = self._artifact_store.persist(
                tool_use_id=block.tool_use_id,
                content=block.content,
                is_error=block.is_error,
            )
            replacement_block = self._create_reference_block(block, artifact)
            if replacement_block is None:
                continue
            replacement_blocks[block_index] = replacement_block
            artifacts.append(artifact)
            remaining_total_bytes = sum(
                self._content_size_bytes(candidate)
                for candidate in replacement_blocks
                if isinstance(candidate, ToolResultBlock)
            )

        if not artifacts:
            return ToolResultBudgetResult(
                snapshot=snapshot,
                artifacts=(),
                original_total_bytes=original_total_bytes,
                remaining_total_bytes=remaining_total_bytes,
            )
        compacted_last_message = ModelMessage(
            role=last_message.role,
            content=tuple(replacement_blocks),
        )
        compacted_snapshot = ContextInputSnapshot(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=(*snapshot.messages[:-1], compacted_last_message),
            system_prompt=snapshot.system_prompt,
            tools=snapshot.tools,
        )
        return ToolResultBudgetResult(
            snapshot=compacted_snapshot,
            artifacts=tuple(artifacts),
            original_total_bytes=original_total_bytes,
            remaining_total_bytes=remaining_total_bytes,
        )

    def _create_reference_block(
        self,
        block: ToolResultBlock,
        artifact: ToolResultArtifact,
    ) -> ToolResultBlock | None:
        """逐步缩短预览，确保 Artifact 引用块确实能释放上下文预算。"""

        serialized_content = self._serialize_content(block)
        preview = serialized_content[: self._preview_max_characters]
        original_size_bytes = self._content_size_bytes(block)
        while True:
            replacement = ToolResultBlock(
                tool_use_id=block.tool_use_id,
                is_error=block.is_error,
                content={
                    "artifact_ref": artifact.relative_path,
                    "preview": preview,
                    "notice": "完整结果已保存；如需完整内容，请重新执行该工具调用。",
                },
            )
            if self._content_size_bytes(replacement) < original_size_bytes:
                return replacement
            if not preview:
                return None
            preview = preview[: len(preview) // 2]

    @classmethod
    def _content_size_bytes(cls, block: ToolResultBlock) -> int:
        return len(cls._serialize_content(block).encode("utf-8"))

    @staticmethod
    def _serialize_content(block: ToolResultBlock) -> str:
        return json.dumps(
            dict(block.content),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
