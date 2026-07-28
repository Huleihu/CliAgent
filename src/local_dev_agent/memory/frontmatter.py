"""长期记忆 Markdown 与 YAML frontmatter 的受控编解码。"""

from __future__ import annotations

from collections.abc import Mapping

import yaml

from .errors import MemoryFrontmatterError
from .schema import MemoryEntry, MemoryType


def parse_memory_document(content: str) -> MemoryEntry:
    """解析单个记忆文件，要求完整 frontmatter 与非空正文。"""

    if not isinstance(content, str):
        raise TypeError("长期记忆文档内容必须是字符串。")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise MemoryFrontmatterError("长期记忆文档必须以 YAML frontmatter 分隔符“---”开头。")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise MemoryFrontmatterError("长期记忆文档的 YAML frontmatter 缺少结束分隔符“---”。")
    try:
        metadata = yaml.safe_load("".join(lines[1:closing_index]))
    except yaml.YAMLError as error:
        raise MemoryFrontmatterError("长期记忆文档的 YAML frontmatter 无法解析。") from error
    if not isinstance(metadata, Mapping):
        raise MemoryFrontmatterError("长期记忆文档的 YAML frontmatter 必须是对象。")
    try:
        return MemoryEntry(
            memory_id=metadata.get("name"),
            memory_type=MemoryType(metadata.get("type")),
            description=metadata.get("description"),
            content="".join(lines[closing_index + 1:]),
        )
    except (TypeError, ValueError) as error:
        raise MemoryFrontmatterError(str(error)) from error


def render_memory_document(entry: MemoryEntry) -> str:
    """以稳定字段顺序生成可人工阅读的 Markdown 记忆文件。"""

    if not isinstance(entry, MemoryEntry):
        raise TypeError("entry 必须是 MemoryEntry 对象。")
    frontmatter = yaml.safe_dump(
        {
            "name": entry.memory_id,
            "description": entry.description,
            "type": entry.memory_type.value,
        },
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{frontmatter}---\n\n{entry.content}\n"
