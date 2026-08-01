"""Team 领域默认标识生成器。"""

from uuid import uuid4


class UuidTeamIdGenerator:
    """为不同 Team 实体生成带类别前缀的 UUID 标识。"""

    def new_id(self, *, kind: str) -> str:
        """生成路径安全且可读的标识，具体唯一性仍由仓储保证。"""

        if not isinstance(kind, str) or not kind.strip() or any(
            separator in kind for separator in ("/", "\\")
        ):
            raise ValueError("字段“kind”必须是不含路径分隔符的非空字符串。")
        return f"{kind.strip()}-{uuid4()}"
