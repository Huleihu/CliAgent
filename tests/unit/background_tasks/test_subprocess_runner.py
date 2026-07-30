from pathlib import Path
import subprocess

import pytest

from local_dev_agent.background_tasks import (
    CommandExecutionTimeoutError,
    SubprocessCommandRunner,
)


def test_subprocess_runner_combines_output_and_applies_its_output_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=3, stdout="abc", stderr="def")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = SubprocessCommandRunner(max_output_chars=4).run(
        command="示例命令",
        working_directory=tmp_path,
    )

    assert result.exit_code == 3
    assert result.output == "abcd"
    assert calls == [
        {
            "shell": True,
            "cwd": tmp_path,
            "capture_output": True,
            "text": True,
            "errors": "replace",
            "timeout": 120,
            "check": False,
        }
    ]


def test_subprocess_runner_maps_timeout_to_a_stable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="示例命令", timeout=3)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(CommandExecutionTimeoutError, match="超过 3 秒时限"):
        SubprocessCommandRunner(timeout_seconds=3).run(
            command="示例命令",
            working_directory=tmp_path,
        )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds”必须是正数"),
        ({"max_output_chars": 0}, "max_output_chars”必须是正整数"),
    ],
)
def test_subprocess_runner_validates_configuration(
    arguments: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SubprocessCommandRunner(**arguments)  # type: ignore[arg-type]
