"""工具调用的不可变数据契约与基础校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .errors import ToolValidationError


DELEGATION_TOOL_TAG = "delegation"
"""标记会创建独立子运行的本地工具标签。"""

CONTEXT_COMPACTION_TOOL_TAG = "context_compaction"
"""标记仅由 Runtime 解释、请求下一轮压缩上下文的控制工具。"""


def _require_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"字段“{field_name}”必须是非空字符串。")


def _copy_json_object(field_name: str, value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ToolValidationError(f"字段“{field_name}”必须是对象。")
    copied_value = dict(value)
    try:
        json.dumps(copied_value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ToolValidationError(
            f"字段“{field_name}”必须只包含 JSON 原生值。"
        ) from error
    return MappingProxyType(copied_value)


def _validate_parameters_schema(parameters: Mapping[str, object]) -> Mapping[str, object]:
    copied_parameters = _copy_json_object("parameters", parameters)
    if copied_parameters.get("type") != "object":
        raise ToolValidationError("工具参数 schema 的 type 必须为“object”。")
    properties = copied_parameters.get("properties")
    if not isinstance(properties, Mapping):
        raise ToolValidationError("工具参数 schema 的 properties 必须是对象。")
    required = copied_parameters.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(field_name, str) for field_name in required
    ):
        raise ToolValidationError("工具参数 schema 的 required 必须是字符串列表。")
    missing = sorted(field_name for field_name in required if field_name not in properties)
    if missing:
        raise ToolValidationError(
            f"工具参数 schema 的 required 字段未在 properties 中声明：{', '.join(missing)}。"
        )
    return copied_parameters


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """描述一个可被模型选择、由运行时受控执行的工具。"""

    name: str
    description: str
    parameters: Mapping[str, object]
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("name", self.name)
        _require_text("description", self.description)
        object.__setattr__(self, "parameters", _validate_parameters_schema(self.parameters))
        if not isinstance(self.tags, tuple) or not all(
            isinstance(tag, str) and tag for tag in self.tags
        ):
            raise ToolValidationError("工具标签必须是非空字符串元组。")


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """一次由模型工具调用块转换而来的标准化调用请求。"""

    name: str
    arguments: Mapping[str, object]
    call_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("name", self.name)
        object.__setattr__(self, "arguments", _copy_json_object("arguments", self.arguments))
        if self.call_id is not None:
            _require_text("call_id", self.call_id)


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """一次工具执行所属的运行、步骤和模型调用关联。"""

    session_id: str
    run_id: str
    step_id: str
    call_id: str | None = None

    def __post_init__(self) -> None:
        """确保工具能够在不依赖全局状态的前提下追溯调用来源。"""

        _require_text("session_id", self.session_id)
        _require_text("run_id", self.run_id)
        _require_text("step_id", self.step_id)
        if self.call_id is not None:
            _require_text("call_id", self.call_id)


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """工具执行成功或失败后的统一、可回填结果。"""

    name: str
    success: bool
    data: Mapping[str, object] | None
    error: Mapping[str, str] | None
    duration_ms: float
    call_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("name", self.name)
        if not isinstance(self.success, bool):
            raise ToolValidationError("工具调用结果的 success 必须是布尔值。")
        if not isinstance(self.duration_ms, (int, float)) or self.duration_ms < 0:
            raise ToolValidationError("工具调用结果的 duration_ms 必须是非负数。")
        if self.call_id is not None:
            _require_text("call_id", self.call_id)
        if self.success:
            if self.error is not None:
                raise ToolValidationError("成功的工具调用结果不能包含错误信息。")
            object.__setattr__(self, "data", _copy_json_object("data", self.data))
        else:
            if self.data is not None or not isinstance(self.error, Mapping):
                raise ToolValidationError("失败的工具调用结果只能包含结构化错误信息。")
            error_type = self.error.get("type")
            error_message = self.error.get("message")
            _require_text("error.type", error_type)
            _require_text("error.message", error_message)
            object.__setattr__(self, "error", MappingProxyType(dict(self.error)))

    @classmethod
    def succeeded(
        cls, *, name: str, data: Mapping[str, object], duration_ms: float, call_id: str | None
    ) -> "ToolCallResult":
        """构造不携带错误信息的成功结果。"""

        return cls(name, True, data, None, duration_ms, call_id)

    @classmethod
    def failed(
        cls, *, name: str, error: Exception, duration_ms: float, call_id: str | None
    ) -> "ToolCallResult":
        """将内部错误收束为可安全回填的结构化失败结果。"""

        return cls(
            name,
            False,
            None,
            {"type": error.__class__.__name__, "message": str(error)},
            duration_ms,
            call_id,
        )
