"""运行时编排服务产生的应用错误。"""


class SessionNotFoundError(ValueError):
    """当输入事件引用的会话尚未保存时抛出。"""

    def __init__(self, *, session_id: str) -> None:
        super().__init__(f"找不到用户输入事件关联的会话“{session_id}”。")
        self.session_id = session_id


class UnsupportedModelResponseError(ValueError):
    """当最小 Agent Loop 收到尚未实现处理分支的模型响应时抛出。"""

    def __init__(self, *, stop_reason: str) -> None:
        super().__init__(
            f"最小 Agent Loop 暂不支持停止原因“{stop_reason}”对应的模型响应。"
        )
        self.stop_reason = stop_reason


class OutputContinuationToolUseError(ValueError):
    """当截断恢复流出现工具调用而无法安全提交时抛出。"""

    def __init__(self) -> None:
        super().__init__(
            "输出截断恢复仅支持纯文本响应；检测到工具调用，未执行任何工具或持久化中间响应。"
        )


class OutputContinuationExhaustedError(ValueError):
    """当临时纯文本续写耗尽上限仍未正常结束时抛出。"""

    def __init__(self, *, max_continuations: int) -> None:
        super().__init__(
            f"输出截断恢复已达到最大续写次数“{max_continuations}”，仍未得到完整响应。"
        )
        self.max_continuations = max_continuations


class AgentLoopExhaustedError(ValueError):
    """当 Agent Loop 达到允许的最大模型调用轮次时抛出。"""

    def __init__(self, *, max_turns: int) -> None:
        super().__init__(f"Agent Loop 已达到最大模型调用轮次“{max_turns}”。")
        self.max_turns = max_turns
