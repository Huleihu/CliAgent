import pytest

from local_dev_agent.teams import TeamAutonomousWorkItem
from local_dev_agent.teams.autonomous_work_prompt import format_autonomous_work_prompt


def test_autonomous_work_prompt_requires_task_completion_after_real_work() -> None:
    prompt = format_autonomous_work_prompt(
        TeamAutonomousWorkItem(
            task_id="task-api",
            subject="实现登录 API。",
            description="新增登录端点。",
        )
    )

    assert "task_complete" in prompt
    assert 'task_id="task-api"' in prompt
    assert "不要认领其他任务" in prompt


def test_autonomous_work_prompt_handles_missing_description_and_wrong_type() -> None:
    prompt = format_autonomous_work_prompt(
        TeamAutonomousWorkItem(
            task_id="task-api",
            subject="实现登录 API。",
            description="",
        )
    )

    assert "（未提供额外说明）" in prompt
    with pytest.raises(TypeError, match="work_item 必须是"):
        format_autonomous_work_prompt(object())  # type: ignore[arg-type]
