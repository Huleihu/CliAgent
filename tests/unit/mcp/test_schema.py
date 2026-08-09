from __future__ import annotations

import unittest

from local_dev_agent.mcp.errors import McpNameValidationError, McpToolDefinitionError
from local_dev_agent.mcp.schema import (
    McpToolAnnotations,
    McpToolDefinition,
    build_mcp_tool_name,
    normalize_mcp_name,
    validate_unique_mcp_tool_names,
)


class McpSchemaTests(unittest.TestCase):
    def test_规范化服务与工具名称并构造稳定公开名称(self) -> None:
        self.assertEqual(normalize_mcp_name("jira.prod", field_name="服务名"), "jira_prod")
        self.assertEqual(normalize_mcp_name("create issue", field_name="工具名"), "create_issue")
        self.assertEqual(
            build_mcp_tool_name("jira.prod", "create issue"),
            "mcp__jira_prod__create_issue",
        )

    def test_拒绝控制字符与无法形成安全片段的名称(self) -> None:
        with self.assertRaisesRegex(McpNameValidationError, "控制字符"):
            normalize_mcp_name("docs\x00", field_name="服务名")
        with self.assertRaisesRegex(McpNameValidationError, "英文字母或数字"):
            normalize_mcp_name("中文", field_name="工具名")

    def test_校验嵌套输入schema并切断外部对象别名(self) -> None:
        source_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询词"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"tag": {"type": "string"}},
                        "required": ["tag"],
                    },
                },
            },
            "required": ["query"],
        }
        tool = McpToolDefinition("search", "搜索文档", source_schema)
        source_schema["properties"]["query"]["type"] = "boolean"

        self.assertEqual(tool.input_schema["properties"]["query"]["type"], "string")
        self.assertEqual(tool.input_schema["required"], ["query"])

    def test_拒绝当前本地校验器无法一致执行的schema(self) -> None:
        with self.assertRaisesRegex(McpToolDefinitionError, "不支持的字段"):
            McpToolDefinition(
                "search",
                "搜索文档",
                {"type": "object", "additionalProperties": True},
            )
        with self.assertRaisesRegex(McpToolDefinitionError, "不存在的属性"):
            McpToolDefinition(
                "search",
                "搜索文档",
                {"type": "object", "properties": {}, "required": ["query"]},
            )

    def test_只读标注默认收窄破坏性提示(self) -> None:
        annotations = McpToolAnnotations.from_mcp({"readOnlyHint": True, "title": "搜索"})

        self.assertTrue(annotations.read_only_hint)
        self.assertFalse(annotations.destructive_hint)
        with self.assertRaisesRegex(McpToolDefinitionError, "同时声明"):
            McpToolAnnotations.from_mcp({"readOnlyHint": True, "destructiveHint": True})

    def test_拒绝规范化后冲突的工具名(self) -> None:
        tools = (
            McpToolDefinition("create issue", "创建工单", {"type": "object"}),
            McpToolDefinition("create_issue", "创建工单", {"type": "object"}),
        )

        with self.assertRaisesRegex(McpToolDefinitionError, "名称规范化后发生冲突"):
            validate_unique_mcp_tool_names("jira", tools)
