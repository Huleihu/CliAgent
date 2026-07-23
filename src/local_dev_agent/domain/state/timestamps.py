"""状态对象共用的时间规范化规则。"""

from datetime import datetime, timezone


def normalize_utc_timestamp(timestamp: datetime, *, subject: str) -> datetime:
    """将带时区时间转换为 UTC，拒绝会造成持久化歧义的无时区时间。"""

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{subject}时间戳必须包含时区信息。")
    return timestamp.astimezone(timezone.utc)
