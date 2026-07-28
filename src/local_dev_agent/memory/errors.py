"""S09 长期记忆的明确错误类型。"""

from pathlib import Path


class MemoryFrontmatterError(ValueError):
    """当记忆 Markdown 的 frontmatter 不符合受控格式时抛出。"""


class CorruptedMemoryFileError(RuntimeError):
    """当磁盘中的记忆文件损坏或与受控文件名不一致时抛出。"""

    def __init__(self, path: Path) -> None:
        super().__init__(f"长期记忆文件“{path}”已损坏或格式不合法。")
        self.path = path
