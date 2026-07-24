import pytest

from local_dev_agent.tools.builtin import ReadFileTool
from local_dev_agent.tools.errors import ToolExecutionError, ToolValidationError


def test_read_file_returns_the_requested_line_range_and_metadata(tmp_path) -> None:
    (tmp_path / "README.md").write_text("第一行\n第二行\n第三行\n第四行", encoding="utf-8")
    tool = ReadFileTool(tmp_path)

    result = tool.run({"path": "README.md", "start_line": 2, "max_lines": 2})

    assert result == {
        "path": "README.md",
        "content": "第二行\n第三行",
        "total_lines": 4,
        "truncated": True,
    }


def test_read_file_marks_a_large_result_as_truncated(tmp_path) -> None:
    (tmp_path / "large.txt").write_text("a" * 20_001, encoding="utf-8")
    tool = ReadFileTool(tmp_path)

    result = tool.run({"path": "large.txt", "max_lines": 1})

    assert result["content"] == "a" * 20_000
    assert result["truncated"] is True


@pytest.mark.parametrize("path", ["..", "/tmp/secret.txt"])
def test_read_file_rejects_workspace_escape_paths(tmp_path, path) -> None:
    tool = ReadFileTool(tmp_path)

    with pytest.raises(ToolValidationError, match="工作区边界|绝对路径或上级目录"):
        tool.run({"path": path})


def test_read_file_rejects_directories_and_non_utf8_files(tmp_path) -> None:
    (tmp_path / "directory").mkdir()
    (tmp_path / "binary.bin").write_bytes(b"\x00\xff")
    tool = ReadFileTool(tmp_path)

    with pytest.raises(ToolExecutionError, match="不是普通文件"):
        tool.run({"path": "directory"})
    with pytest.raises(ToolExecutionError, match="UTF-8 文本"):
        tool.run({"path": "binary.bin"})


@pytest.mark.parametrize(
    "arguments",
    [
        {"path": "README.md", "start_line": 0},
        {"path": "README.md", "max_lines": 1_001},
        {"path": "README.md", "max_lines": True},
    ],
)
def test_read_file_rejects_invalid_line_arguments(tmp_path, arguments) -> None:
    (tmp_path / "README.md").write_text("内容", encoding="utf-8")
    tool = ReadFileTool(tmp_path)

    with pytest.raises(ToolValidationError):
        tool.run(arguments)
