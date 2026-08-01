"""将 Team 收件箱事实转换为独立 Run 输入的纯格式化函数。"""

from .schema import TeamMessage


def format_inbox_prompt(messages: tuple[TeamMessage, ...]) -> str:
    """显式标记消息来源，避免伪装为用户原始 Transcript。"""

    lines = ["[Team 收件箱]"]
    for message in messages:
        lines.append(
            f"#{message.sequence} 来自 {message.sender_member_id}"
            f"（{message.message_type.value}）：{message.content}"
        )
    return "\n".join(lines)
