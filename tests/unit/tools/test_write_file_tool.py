import pytest

from local_dev_agent.tools.builtin import WriteFileTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


def test_write_file_creates_parent_directories_and_reports_utf8_bytes(tmp_path) -> None:
    tool = WriteFileTool(tmp_path)

    result = tool.run({"path": "notes/todo.txt", "content": "完成：权限工具"})

    assert result == {"path": "notes/todo.txt", "bytes_written": 21}
    assert (tmp_path / "notes" / "todo.txt").read_text(encoding="utf-8") == "完成：权限工具"


def test_write_file_overwrites_an_existing_regular_file(tmp_path) -> None:
    target_file = tmp_path / "status.txt"
    target_file.write_text("旧内容", encoding="utf-8")
    tool = WriteFileTool(tmp_path)

    result = tool.run({"path": "status.txt", "content": "新内容"})

    assert result == {"path": "status.txt", "bytes_written": 9}
    assert target_file.read_text(encoding="utf-8") == "新内容"


def test_write_file_preserves_the_given_utf8_line_endings(tmp_path) -> None:
    content = "第一行\r\n第二行\n"
    tool = WriteFileTool(tmp_path)

    result = tool.run({"path": "lines.txt", "content": content})

    assert result == {"path": "lines.txt", "bytes_written": len(content.encode("utf-8"))}
    assert (tmp_path / "lines.txt").read_bytes() == content.encode("utf-8")


@pytest.mark.parametrize("path", ["..", "../outside.txt", "/tmp/outside.txt"])
def test_write_file_rejects_workspace_escape_paths(tmp_path, path) -> None:
    tool = WriteFileTool(tmp_path)

    with pytest.raises(ToolValidationError, match="工作区边界|绝对路径或上级目录"):
        tool.run({"path": path, "content": "测试"})


def test_write_file_rejects_a_directory_target(tmp_path) -> None:
    (tmp_path / "directory").mkdir()
    tool = WriteFileTool(tmp_path)

    with pytest.raises(ToolExecutionError, match="不是普通文件"):
        tool.run({"path": "directory", "content": "测试"})


@pytest.mark.parametrize(
    "arguments",
    [
        {"content": "测试"},
        {"path": "file.txt"},
        {"path": "", "content": "测试"},
        {"path": "file.txt", "content": 1},
    ],
)
def test_write_file_rejects_invalid_arguments(tmp_path, arguments) -> None:
    tool = WriteFileTool(tmp_path)

    with pytest.raises(ToolValidationError):
        tool.run(arguments)
