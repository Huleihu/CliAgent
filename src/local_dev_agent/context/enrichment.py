"""模型请求派生视图的可替换增强端口。"""

from typing import Protocol

from .budget import ContextInputSnapshot


class ContextInputSnapshotEnricher(Protocol):
    """仅转换派生请求视图，不得修改原始 Transcript 或持久化状态。"""

    def enrich(self, snapshot: ContextInputSnapshot) -> ContextInputSnapshot:
        """基于已验证的快照返回新的上下文快照。"""
