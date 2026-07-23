"""状态仓储读写时产生的领域外错误。"""

from pathlib import Path


class CorruptedStateFileError(ValueError):
    """当状态文件无法解析或不符合支持的结构时抛出。"""

    def __init__(self, *, path: Path) -> None:
        super().__init__(f"状态文件“{path}”已损坏或格式不受支持。")
        self.path = path


class StateVersionConflictError(ValueError):
    """当旧状态快照尝试覆盖已保存的新版本时抛出。"""

    def __init__(self, *, entity_name: str, entity_id: str) -> None:
        super().__init__(
            f"{entity_name}“{entity_id}”的状态版本冲突，"
            "请先读取最新状态后再保存。"
        )
        self.entity_name = entity_name
        self.entity_id = entity_id
