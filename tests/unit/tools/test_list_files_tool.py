import pytest

from local_dev_agent.tools.builtin import ListFilesTool
from local_dev_agent.tools.errors import ToolValidationError


def test_list_files_returns_sorted_workspace_relative_paths_and_honors_pattern(tmp_path) -> None:
    (tmp_path / "zeta.py").write_text("zeta", encoding="utf-8")
    source_directory = tmp_path / "src"
    source_directory.mkdir()
    (source_directory / "alpha.py").write_text("alpha", encoding="utf-8")
    (source_directory / "notes.txt").write_text("notes", encoding="utf-8")
    tool = ListFilesTool(tmp_path)

    result = tool.run({"directory": "src", "pattern": "*.py"})

    assert result == {"files": ["src/alpha.py"], "truncated": False}


def test_list_files_limits_results_and_reports_truncation(tmp_path) -> None:
    for name in ("c.txt", "a.txt", "b.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    tool = ListFilesTool(tmp_path)

    result = tool.run({"pattern": "*.txt", "limit": 2})

    assert result == {"files": ["a.txt", "b.txt"], "truncated": True}


@pytest.mark.parametrize("directory", ["..", "/tmp"])
def test_list_files_rejects_workspace_escape_paths(tmp_path, directory) -> None:
    tool = ListFilesTool(tmp_path)

    with pytest.raises(ToolValidationError, match="工作区边界|绝对路径或上级目录"):
        tool.run({"directory": directory})


@pytest.mark.parametrize("arguments", [{"pattern": "../*.py"}, {"limit": 0}, {"limit": True}])
def test_list_files_rejects_unsafe_patterns_and_invalid_limits(tmp_path, arguments) -> None:
    tool = ListFilesTool(tmp_path)

    with pytest.raises(ToolValidationError):
        tool.run(arguments)
