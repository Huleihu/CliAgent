import pytest

from local_dev_agent.tools.builtin import EditFileTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


def test_edit_file_replaces_only_the_first_exact_match(tmp_path) -> None:
    target_file = tmp_path / "status.txt"
    target_file.write_text("待办\n待办\n完成", encoding="utf-8")
    tool = EditFileTool(tmp_path)

    result = tool.run(
        {"path": "status.txt", "old_text": "待办", "new_text": "进行中"}
    )

    assert result == {"path": "status.txt", "replacements": 1}
    assert target_file.read_text(encoding="utf-8") == "进行中\n待办\n完成"


def test_edit_file_allows_an_empty_replacement_to_delete_text(tmp_path) -> None:
    target_file = tmp_path / "status.txt"
    target_file.write_text("前缀-删除我-后缀", encoding="utf-8")
    tool = EditFileTool(tmp_path)

    result = tool.run(
        {"path": "status.txt", "old_text": "删除我-", "new_text": ""}
    )

    assert result == {"path": "status.txt", "replacements": 1}
    assert target_file.read_text(encoding="utf-8") == "前缀-后缀"


@pytest.mark.parametrize("path", ["..", "../outside.txt", "/tmp/outside.txt"])
def test_edit_file_rejects_workspace_escape_paths(tmp_path, path) -> None:
    tool = EditFileTool(tmp_path)

    with pytest.raises(ToolValidationError, match="工作区边界|绝对路径或上级目录"):
        tool.run({"path": path, "old_text": "旧", "new_text": "新"})


def test_edit_file_rejects_missing_text_and_non_utf8_content(tmp_path) -> None:
    target_file = tmp_path / "status.txt"
    target_file.write_text("已有文本", encoding="utf-8")
    binary_file = tmp_path / "binary.bin"
    binary_file.write_bytes(b"\x00\xff")
    tool = EditFileTool(tmp_path)

    with pytest.raises(ToolExecutionError, match="未找到"):
        tool.run({"path": "status.txt", "old_text": "缺失", "new_text": "新"})
    with pytest.raises(ToolExecutionError, match="UTF-8 文本"):
        tool.run({"path": "binary.bin", "old_text": "旧", "new_text": "新"})


@pytest.mark.parametrize(
    "arguments",
    [
        {"old_text": "旧", "new_text": "新"},
        {"path": "status.txt", "new_text": "新"},
        {"path": "status.txt", "old_text": "旧"},
        {"path": "status.txt", "old_text": "", "new_text": "新"},
        {"path": "status.txt", "old_text": "旧", "new_text": 1},
    ],
)
def test_edit_file_rejects_invalid_arguments(tmp_path, arguments) -> None:
    (tmp_path / "status.txt").write_text("旧", encoding="utf-8")
    tool = EditFileTool(tmp_path)

    with pytest.raises(ToolValidationError):
        tool.run(arguments)
