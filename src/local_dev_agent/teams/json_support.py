"""Team JSON 适配器共享的原子文件与路径安全工具。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def require_safe_identifier(field_name: str, value: str) -> str:
    """拒绝会将 Team 仓储路径带出预定根目录的标识。"""

    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"字段“{field_name}”不能包含路径分隔符且必须非空。")
    return value.strip()


def write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    """同目录写入、fsync 和替换，避免中断留下半截 Team 快照。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def read_json_object(path: Path) -> dict[str, object]:
    """读取 JSON 对象，把非对象根节点留给调用方统一诊断。"""

    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("JSON 根节点必须是对象。")
    return payload
