"""五段式 cron 最小安全子集的解析与匹配。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .errors import CronExpressionValidationError


@dataclass(frozen=True, slots=True)
class CronField:
    """一个已解析字段允许的值与字面未受限语义。"""

    source: str
    allowed_values: frozenset[int]
    is_unconstrained: bool

    def __post_init__(self) -> None:
        """拒绝不完整字段，保证匹配器不依赖可变容器。"""

        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("字段“source”必须是非空字符串。")
        if not isinstance(self.allowed_values, frozenset) or not self.allowed_values:
            raise ValueError("字段“allowed_values”必须是非空 frozenset。")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in self.allowed_values):
            raise ValueError("字段“allowed_values”必须只包含整数。")
        if not isinstance(self.is_unconstrained, bool):
            raise ValueError("字段“is_unconstrained”必须是布尔值。")

    def matches(self, value: int) -> bool:
        """判断字段是否允许一个已经由调用方限定范围的数值。"""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("待匹配的 cron 字段值必须是整数。")
        return value in self.allowed_values


@dataclass(frozen=True, slots=True)
class CronExpression:
    """解析后的五段式表达式，DOM/DOW 保留独立的限制标记。"""

    source: str
    minute: CronField
    hour: CronField
    day_of_month: CronField
    month: CronField
    day_of_week: CronField

    def __post_init__(self) -> None:
        """保证所有字段来自同一完整解析结果。"""

        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("字段“source”必须是非空字符串。")
        if not all(
            isinstance(field, CronField)
            for field in (
                self.minute,
                self.hour,
                self.day_of_month,
                self.month,
                self.day_of_week,
            )
        ):
            raise ValueError("cron 表达式字段必须是 CronField。")

    def matches(self, occurred_at: datetime) -> bool:
        """按 cron DOM/DOW OR 语义判断一个带时区的本地时间。"""

        if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
            raise ValueError("occurred_at 必须是带时区的 datetime。")
        if not (
            self.minute.matches(occurred_at.minute)
            and self.hour.matches(occurred_at.hour)
            and self.month.matches(occurred_at.month)
        ):
            return False

        day_of_month_matches = self.day_of_month.matches(occurred_at.day)
        cron_day_of_week = (occurred_at.weekday() + 1) % 7
        day_of_week_matches = self.day_of_week.matches(cron_day_of_week)
        if self.day_of_month.is_unconstrained and self.day_of_week.is_unconstrained:
            return True
        if self.day_of_month.is_unconstrained:
            return day_of_week_matches
        if self.day_of_week.is_unconstrained:
            return day_of_month_matches
        return day_of_month_matches or day_of_week_matches


@dataclass(frozen=True, slots=True)
class _FieldSpecification:
    """描述单个 cron 字段的取值范围，避免散落的魔法数字。"""

    name: str
    minimum: int
    maximum: int


_FIELD_SPECIFICATIONS = (
    _FieldSpecification("分钟", 0, 59),
    _FieldSpecification("小时", 0, 23),
    _FieldSpecification("日", 1, 31),
    _FieldSpecification("月", 1, 12),
    _FieldSpecification("星期", 0, 6),
)


def parse_cron_expression(expression: str) -> CronExpression:
    """解析首版允许的五段式 cron，并在注册前拒绝全部非法写法。"""

    if not isinstance(expression, str) or not expression.strip():
        raise CronExpressionValidationError("cron 表达式必须是非空字符串。")
    sources = expression.split()
    if len(sources) != 5:
        raise CronExpressionValidationError("cron 表达式必须恰好包含五个字段。")
    fields = tuple(
        _parse_field(source, specification)
        for source, specification in zip(sources, _FIELD_SPECIFICATIONS, strict=True)
    )
    return CronExpression(
        source=" ".join(sources),
        minute=fields[0],
        hour=fields[1],
        day_of_month=fields[2],
        month=fields[3],
        day_of_week=fields[4],
    )


def cron_matches(expression: CronExpression, occurred_at: datetime) -> bool:
    """提供显式函数入口，供调度器复用已解析表达式进行匹配。"""

    if not isinstance(expression, CronExpression):
        raise TypeError("expression 必须是 CronExpression 对象。")
    return expression.matches(occurred_at)


def _parse_field(source: str, specification: _FieldSpecification) -> CronField:
    """解析一个字段的单一安全形式，不接受混合复合表达式。"""

    if source == "*":
        return CronField(
            source=source,
            allowed_values=frozenset(
                range(specification.minimum, specification.maximum + 1)
            ),
            is_unconstrained=True,
        )
    if source.startswith("*/"):
        return _parse_step_field(source, specification)
    if "," in source:
        return _parse_list_field(source, specification)
    if "-" in source:
        return _parse_range_field(source, specification)
    return CronField(
        source=source,
        allowed_values=frozenset({_parse_value(source, specification)}),
        is_unconstrained=False,
    )


def _parse_step_field(source: str, specification: _FieldSpecification) -> CronField:
    """仅支持从字段最小值开始的 */N 步长形式。"""

    step_text = source[2:]
    step = _parse_positive_integer(step_text, specification)
    return CronField(
        source=source,
        allowed_values=frozenset(
            range(specification.minimum, specification.maximum + 1, step)
        ),
        is_unconstrained=False,
    )


def _parse_list_field(source: str, specification: _FieldSpecification) -> CronField:
    """仅支持 N,M,... 数值列表，避免首版扩大为混合语法。"""

    parts = source.split(",")
    if not all(parts):
        raise _validation_error(specification, source, "列表不能包含空项")
    values = frozenset(_parse_value(part, specification) for part in parts)
    return CronField(source=source, allowed_values=values, is_unconstrained=False)


def _parse_range_field(source: str, specification: _FieldSpecification) -> CronField:
    """仅支持闭区间 N-M，不支持范围步长或反向范围。"""

    parts = source.split("-")
    if len(parts) != 2 or not all(parts):
        raise _validation_error(specification, source, "范围必须写为 N-M")
    start = _parse_value(parts[0], specification)
    end = _parse_value(parts[1], specification)
    if start > end:
        raise _validation_error(specification, source, "范围起点不能大于终点")
    return CronField(
        source=source,
        allowed_values=frozenset(range(start, end + 1)),
        is_unconstrained=False,
    )


def _parse_positive_integer(source: str, specification: _FieldSpecification) -> int:
    """读取步长；零、负数和超过字段宽度的数值均没有安全语义。"""

    if not source.isascii() or not source.isdecimal():
        raise _validation_error(specification, source, "步长必须是正整数")
    value = int(source)
    if value < 1 or value > specification.maximum - specification.minimum + 1:
        raise _validation_error(specification, source, "步长超出允许范围")
    return value


def _parse_value(source: str, specification: _FieldSpecification) -> int:
    """读取字段内的十进制数值，并给出带字段名的稳定错误。"""

    if not source.isascii() or not source.isdecimal():
        raise _validation_error(specification, source, "必须是十进制整数")
    value = int(source)
    if not specification.minimum <= value <= specification.maximum:
        raise _validation_error(
            specification,
            source,
            f"必须位于 {specification.minimum}-{specification.maximum} 范围内",
        )
    return value


def _validation_error(
    specification: _FieldSpecification,
    source: str,
    reason: str,
) -> CronExpressionValidationError:
    """统一表达字段解析错误，避免工具层自行拼接诊断。"""

    return CronExpressionValidationError(
        f"cron 字段“{specification.name}”值“{source}”无效：{reason}。"
    )
