"""MCP Server 数据进入本地工具池前的安全契约与校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from local_dev_agent.mcp.errors import McpNameValidationError, McpToolDefinitionError

_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HAS_ALPHANUMERIC_PATTERN = re.compile(r"[A-Za-z0-9]")
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_SUPPORTED_SCHEMA_KEYS = frozenset({"type", "properties", "required", "items", "description"})
_SUPPORTED_TYPES = frozenset({"object", "string", "integer", "boolean", "array"})


def normalize_mcp_name(value: str, *, field_name: str) -> str:
    """将协议名称转换为可安全组合到本地工具名中的片段。"""

    if not isinstance(value, str) or not value:
        raise McpNameValidationError(f"MCP {field_name} 必须是非空字符串。")
    if len(value) > 64:
        raise McpNameValidationError(f"MCP {field_name} 不能超过 64 个字符。")
    if _CONTROL_CHARACTER_PATTERN.search(value):
        raise McpNameValidationError(f"MCP {field_name} 不能包含控制字符。")

    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    if not _SAFE_NAME_PATTERN.fullmatch(normalized) or not _HAS_ALPHANUMERIC_PATTERN.search(
        normalized
    ):
        raise McpNameValidationError(
            f"MCP {field_name} 规范化后必须包含至少一个英文字母或数字。"
        )
    return normalized


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """构造稳定且不会与内置工具混淆的 MCP 公开工具名。"""

    normalized_server_name = normalize_mcp_name(server_name, field_name="服务名")
    normalized_tool_name = normalize_mcp_name(tool_name, field_name="工具名")
    public_name = f"mcp__{normalized_server_name}__{normalized_tool_name}"
    if len(public_name) > 128:
        raise McpNameValidationError("MCP 公开工具名不能超过 128 个字符。")
    return public_name


def _copy_json_value(value: Any, *, field_name: str) -> Any:
    """深复制 JSON 值，切断不可信输入对象后续修改带来的别名关系。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _copy_json_value(item, field_name=field_name)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_copy_json_value(item, field_name=field_name) for item in value]
    raise McpToolDefinitionError(f"{field_name} 必须只包含 JSON 兼容的数据类型。")


def _validate_description(value: object, *, field_name: str, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise McpToolDefinitionError(f"{field_name} 必须是非空字符串。")
    if len(value) > 2000 or _CONTROL_CHARACTER_PATTERN.search(value.replace("\n", "").replace("\t", "")):
        raise McpToolDefinitionError(f"{field_name} 包含不允许的控制字符或长度超过限制。")
    return value.strip()


def normalize_mcp_input_schema(input_schema: Mapping[str, object]) -> dict[str, object]:
    """校验并收窄外部 JSON Schema 到本地参数校验器可执行的子集。"""

    if not isinstance(input_schema, Mapping):
        raise McpToolDefinitionError("MCP 工具 inputSchema 必须是对象。")
    return _normalize_schema_node(input_schema, path="inputSchema", require_object=True)


def _normalize_schema_node(
    node: Mapping[str, object], *, path: str, require_object: bool = False
) -> dict[str, object]:
    unsupported_keys = set(node).difference(_SUPPORTED_SCHEMA_KEYS)
    if unsupported_keys:
        formatted_keys = "、".join(sorted(map(str, unsupported_keys)))
        raise McpToolDefinitionError(
            f"MCP 工具 {path} 包含本地参数校验器不支持的字段：{formatted_keys}。"
        )

    schema_type = node.get("type")
    if schema_type not in _SUPPORTED_TYPES:
        raise McpToolDefinitionError(
            f"MCP 工具 {path}.type 必须是受支持的类型：object、string、integer、boolean 或 array。"
        )
    if require_object and schema_type != "object":
        raise McpToolDefinitionError("MCP 工具 inputSchema.type 必须为 object。")

    normalized: dict[str, object] = {"type": schema_type}
    description = _validate_description(
        node.get("description"), field_name=f"MCP 工具 {path}.description", required=False
    )
    if description is not None:
        normalized["description"] = description

    if schema_type == "object":
        properties = node.get("properties", {})
        if not isinstance(properties, Mapping):
            raise McpToolDefinitionError(f"MCP 工具 {path}.properties 必须是对象。")
        normalized_properties: dict[str, object] = {}
        for property_name, property_schema in properties.items():
            if not isinstance(property_name, str) or not property_name or _CONTROL_CHARACTER_PATTERN.search(
                property_name
            ):
                raise McpToolDefinitionError(
                    f"MCP 工具 {path}.properties 的属性名必须是无控制字符的非空字符串。"
                )
            if not isinstance(property_schema, Mapping):
                raise McpToolDefinitionError(
                    f"MCP 工具 {path}.properties.{property_name} 必须是对象。"
                )
            normalized_properties[property_name] = _normalize_schema_node(
                property_schema, path=f"{path}.properties.{property_name}"
            )
        normalized["properties"] = normalized_properties

        required = node.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise McpToolDefinitionError(f"MCP 工具 {path}.required 必须是字符串数组。")
        if len(required) != len(set(required)):
            raise McpToolDefinitionError(f"MCP 工具 {path}.required 不能包含重复属性。")
        unknown_required = set(required).difference(normalized_properties)
        if unknown_required:
            formatted_names = "、".join(sorted(unknown_required))
            raise McpToolDefinitionError(
                f"MCP 工具 {path}.required 声明了不存在的属性：{formatted_names}。"
            )
        normalized["required"] = list(required)
    elif schema_type == "array":
        items = node.get("items")
        if not isinstance(items, Mapping):
            raise McpToolDefinitionError(f"MCP 工具 {path}.items 必须是对象。")
        normalized["items"] = _normalize_schema_node(items, path=f"{path}.items")
    elif "properties" in node or "required" in node or "items" in node:
        raise McpToolDefinitionError(f"MCP 工具 {path} 的 {schema_type} 类型不能声明对象或数组字段。")

    return normalized


@dataclass(frozen=True)
class McpToolAnnotations:
    """经校验后可供本地权限策略参考的 MCP 工具提示。"""

    title: str | None = None
    read_only_hint: bool = False
    destructive_hint: bool = True
    idempotent_hint: bool = False
    open_world_hint: bool = True

    @classmethod
    def from_mcp(cls, annotations: Mapping[str, object] | None) -> "McpToolAnnotations":
        """将 MCP 的 camelCase 标注转换为本地不可变值对象。"""

        if annotations is None:
            return cls()
        if not isinstance(annotations, Mapping):
            raise McpToolDefinitionError("MCP 工具 annotations 必须是对象。")

        title_value = annotations.get("title")
        title = _validate_description(title_value, field_name="MCP 工具 annotations.title", required=False)
        values: dict[str, bool] = {}
        for protocol_name, local_name, default in (
            ("readOnlyHint", "read_only_hint", False),
            ("destructiveHint", "destructive_hint", True),
            ("idempotentHint", "idempotent_hint", False),
            ("openWorldHint", "open_world_hint", True),
        ):
            value = annotations.get(protocol_name, default)
            if not isinstance(value, bool):
                raise McpToolDefinitionError(
                    f"MCP 工具 annotations.{protocol_name} 必须是布尔值。"
                )
            values[local_name] = value

        if values["read_only_hint"] and "destructiveHint" not in annotations:
            values["destructive_hint"] = False
        if values["read_only_hint"] and values["destructive_hint"]:
            raise McpToolDefinitionError(
                "MCP 工具 annotations 不能同时声明只读和破坏性操作。"
            )
        return cls(title=title, **values)


@dataclass(frozen=True)
class McpToolDefinition:
    """已通过本地安全边界的外部 MCP 工具定义。"""

    name: str
    description: str
    input_schema: Mapping[str, object]
    annotations: McpToolAnnotations = field(default_factory=McpToolAnnotations)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise McpToolDefinitionError("MCP 工具 name 必须是非空字符串。")
        if _CONTROL_CHARACTER_PATTERN.search(self.name):
            raise McpToolDefinitionError("MCP 工具 name 不能包含控制字符。")
        object.__setattr__(
            self,
            "description",
            _validate_description(self.description, field_name="MCP 工具 description", required=True),
        )
        object.__setattr__(self, "input_schema", normalize_mcp_input_schema(self.input_schema))
        if not isinstance(self.annotations, McpToolAnnotations):
            raise McpToolDefinitionError("MCP 工具 annotations 必须使用已校验的标注对象。")


@dataclass(frozen=True)
class McpServerConfiguration:
    """组合根提供的 MCP Server 配置；本步不涉及网络传输细节。"""

    name: str

    def __post_init__(self) -> None:
        normalize_mcp_name(self.name, field_name="服务名")

    @property
    def normalized_name(self) -> str:
        """返回用于本地公开工具名的稳定服务片段。"""

        return normalize_mcp_name(self.name, field_name="服务名")


def validate_unique_mcp_tool_names(
    server_name: str, tools: tuple[McpToolDefinition, ...] | list[McpToolDefinition]
) -> tuple[str, ...]:
    """提前发现规范化后的同服务工具名冲突，避免半注册状态。"""

    public_names = tuple(build_mcp_tool_name(server_name, tool.name) for tool in tools)
    if len(public_names) != len(set(public_names)):
        raise McpToolDefinitionError(
            "MCP Server 返回的工具在名称规范化后发生冲突，连接已拒绝。"
        )
    return public_names
