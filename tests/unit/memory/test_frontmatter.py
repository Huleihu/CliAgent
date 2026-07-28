"""长期记忆 Markdown 编解码的单元测试。"""

import pytest

from local_dev_agent.memory import (
    MemoryEntry,
    MemoryFrontmatterError,
    MemoryType,
    parse_memory_document,
    render_memory_document,
)


def test_memory_document_round_trip_preserves_entry() -> None:
    entry = MemoryEntry(
        memory_id="project-auth-rewrite",
        memory_type=MemoryType.PROJECT,
        description="认证重构由合规要求驱动",
        content="保留审批链路。\n\n不要删除审计记录。",
    )

    assert parse_memory_document(render_memory_document(entry)) == entry


@pytest.mark.parametrize(
    "content",
    (
        "正文",
        "---\nname: user-tabs\n",
        "---\n- name: user-tabs\n---\n\n正文",
        "---\nname: user-tabs\ndescription: 描述\ntype: invalid\n---\n\n正文",
        "---\nname: user-tabs\ndescription: 描述\ntype: user\n---\n\n",
    ),
)
def test_memory_document_rejects_invalid_frontmatter(content: str) -> None:
    with pytest.raises(MemoryFrontmatterError):
        parse_memory_document(content)
