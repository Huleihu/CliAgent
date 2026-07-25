"""待办清单仓储产生的领域外错误。"""

from pathlib import Path


class CorruptedTodoFileError(ValueError):
    """当待办清单文件无法解析或结构不受支持时抛出。"""

    def __init__(self, *, path: Path) -> None:
        super().__init__(f"待办清单文件“{path}”已损坏或格式不受支持。")
        self.path = path
