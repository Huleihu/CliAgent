"""工具调用参数的最小 JSON Schema 校验。"""

from __future__ import annotations

from collections.abc import Mapping

from .errors import ToolValidationError


def validate_arguments(
    *,
    tool_name: str,
    parameters: Mapping[str, object],
    arguments: Mapping[str, object],
) -> None:
    """在 Handler 前校验当前工具定义所使用的 JSON Schema 子集。"""

    _validate_value(
        tool_name=tool_name,
        schema=parameters,
        value=arguments,
        location="参数",
    )


def _validate_value(
    *,
    tool_name: str,
    schema: Mapping[str, object],
    value: object,
    location: str,
) -> None:
    value_type = schema.get("type")
    if value_type == "object":
        _validate_object(tool_name=tool_name, schema=schema, value=value, location=location)
        return
    if value_type == "string":
        if not isinstance(value, str):
            _raise_type_error(tool_name, location, "字符串")
        return
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _raise_type_error(tool_name, location, "整数")
        return
    if value_type == "boolean":
        if not isinstance(value, bool):
            _raise_type_error(tool_name, location, "布尔值")
        return
    if value_type == "array":
        _validate_array(tool_name=tool_name, schema=schema, value=value, location=location)
        return
    raise ToolValidationError(
        f"工具“{tool_name}”的参数 schema 在“{location}”使用了不支持的类型“{value_type}”。"
    )


def _validate_object(
    *,
    tool_name: str,
    schema: Mapping[str, object],
    value: object,
    location: str,
) -> None:
    if not isinstance(value, Mapping):
        _raise_type_error(tool_name, location, "对象")
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ToolValidationError(f"工具“{tool_name}”的参数 schema 缺少对象属性定义。")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        raise ToolValidationError(f"工具“{tool_name}”的参数 schema 包含无效的必填字段定义。")

    unknown_fields = sorted(field_name for field_name in value if field_name not in properties)
    if unknown_fields:
        raise ToolValidationError(
            f"工具“{tool_name}”不支持参数：{', '.join(unknown_fields)}。"
        )
    missing_fields = sorted(field_name for field_name in required if field_name not in value)
    if missing_fields:
        raise ToolValidationError(
            f"工具“{tool_name}”缺少必填参数：{', '.join(missing_fields)}。"
        )

    for field_name, field_value in value.items():
        field_schema = properties[field_name]
        if not isinstance(field_schema, Mapping):
            raise ToolValidationError(
                f"工具“{tool_name}”的参数“{field_name}”缺少有效 schema。"
            )
        _validate_value(
            tool_name=tool_name,
            schema=field_schema,
            value=field_value,
            location=f"{location}.{field_name}",
        )


def _validate_array(
    *,
    tool_name: str,
    schema: Mapping[str, object],
    value: object,
    location: str,
) -> None:
    if not isinstance(value, list):
        _raise_type_error(tool_name, location, "数组")
    item_schema = schema.get("items")
    if not isinstance(item_schema, Mapping):
        raise ToolValidationError(f"工具“{tool_name}”的数组参数缺少元素 schema。")
    for index, item in enumerate(value):
        _validate_value(
            tool_name=tool_name,
            schema=item_schema,
            value=item,
            location=f"{location}[{index}]",
        )


def _raise_type_error(tool_name: str, location: str, expected_type: str) -> None:
    raise ToolValidationError(
        f"工具“{tool_name}”的“{location}”必须是{expected_type}。"
    )
