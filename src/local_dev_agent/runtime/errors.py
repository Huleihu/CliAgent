"""运行时编排服务产生的应用错误。"""


class SessionNotFoundError(ValueError):
    """当输入事件引用的会话尚未保存时抛出。"""

    def __init__(self, *, session_id: str) -> None:
        super().__init__(f"找不到用户输入事件关联的会话“{session_id}”。")
        self.session_id = session_id
