"""将已认领的自主工作转换为成员 Runtime 的受控输入。"""

from .schema import TeamAutonomousWorkItem


def format_autonomous_work_prompt(work_item: TeamAutonomousWorkItem) -> str:
    """明确完成工具调用边界，避免成员把模型文本误当作任务已完成。"""

    if not isinstance(work_item, TeamAutonomousWorkItem):
        raise TypeError("work_item 必须是 TeamAutonomousWorkItem 对象。")
    description = work_item.description or "（未提供额外说明）"
    return "\n".join(
        (
            "[S17 自主任务]",
            f"你已成功认领项目任务：{work_item.task_id}",
            f"标题：{work_item.subject}",
            "详细要求：",
            description,
            "",
            "请在当前工作区完成并验证该任务。",
            (
                "仅当任务实际完成后，必须调用 task_complete，"
                f"并传入 task_id=\"{work_item.task_id}\"。"
            ),
            "不要认领其他任务，也不要修改其他任务的归属。",
        )
    )
