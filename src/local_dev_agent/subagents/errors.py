"""子 Agent 委派运行产生的应用错误。"""


class SubagentParentSessionNotFoundError(ValueError):
    """当委派任务关联的父会话未保存时抛出。"""

    def __init__(self, *, session_id: str) -> None:
        super().__init__(f"找不到子 Agent 委派任务关联的父会话“{session_id}”。")
        self.session_id = session_id
