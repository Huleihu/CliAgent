"""工作区文本工具共享的 UTF-8 文件读取能力。"""

from pathlib import Path

from .errors import ToolExecutionError


def read_utf8_text(target_file: Path, path: str) -> str:
    """读取普通 UTF-8 文本文件，并拒绝二进制或无效编码内容。"""

    try:
        data = target_file.read_bytes()
    except OSError as error:
        raise ToolExecutionError(f"无法读取文件：{path}。") from error
    if b"\x00" in data:
        raise ToolExecutionError(f"文件不是可读取的 UTF-8 文本：{path}。")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolExecutionError(f"文件不是可读取的 UTF-8 文本：{path}。") from error
