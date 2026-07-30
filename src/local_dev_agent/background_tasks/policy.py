"""后台执行选择的纯策略。"""


class BackgroundExecutionPolicy:
    """显式模型请求优先，未指定时仅以保守关键词作为兜底。"""

    _SLOW_COMMAND_KEYWORDS = (
        "install",
        "build",
        "test",
        "deploy",
        "compile",
        "docker build",
        "pip install",
        "npm install",
        "cargo build",
        "pytest",
        "make",
    )

    def should_run_in_background(
        self,
        *,
        command: str,
        requested: bool | None,
    ) -> bool:
        """按显式布尔值或命令特征决定是否交由后台服务派发。"""

        if not isinstance(command, str) or not command.strip():
            raise ValueError("字段“command”必须是非空字符串。")
        if requested is not None and not isinstance(requested, bool):
            raise ValueError("字段“requested”必须是布尔值或 None。")
        if requested is not None:
            return requested
        normalized_command = command.lower()
        return any(
            keyword in normalized_command for keyword in self._SLOW_COMMAND_KEYWORDS
        )
