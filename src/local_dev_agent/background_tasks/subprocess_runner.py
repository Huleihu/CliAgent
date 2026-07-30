"""基于本地 shell 的命令执行适配器。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import CommandExecutionTimeoutError
from .schema import CommandExecutionResult


class SubprocessCommandRunner:
    """在固定工作目录同步运行一条 shell 命令，并收束有界文本输出。"""

    def __init__(
        self,
        *,
        timeout_seconds: float = 120,
        max_output_chars: int = 50_000,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("字段“timeout_seconds”必须是正数。")
        if (
            isinstance(max_output_chars, bool)
            or not isinstance(max_output_chars, int)
            or max_output_chars < 1
        ):
            raise ValueError("字段“max_output_chars”必须是正整数。")
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    def run(self, *, command: str, working_directory: Path) -> CommandExecutionResult:
        """在工作区 shell 中执行命令，合并标准输出和错误输出。"""

        if not isinstance(command, str) or not command.strip():
            raise ValueError("字段“command”必须是非空字符串。")
        if not isinstance(working_directory, Path):
            raise TypeError("working_directory 必须是 Path 对象。")
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=working_directory,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CommandExecutionTimeoutError(
                timeout_seconds=self._timeout_seconds
            ) from error
        output = f"{completed.stdout or ''}{completed.stderr or ''}"
        return CommandExecutionResult(
            exit_code=completed.returncode,
            output=output[: self._max_output_chars],
        )
