from datetime import datetime, timezone

import pytest

from local_dev_agent.cron import (
    CronExpressionValidationError,
    cron_matches,
    parse_cron_expression,
)


def _at(
    *,
    year: int = 2026,
    month: int = 7,
    day: int = 30,
    hour: int = 9,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("source", "timestamp"),
    [
        ("* * * * *", _at()),
        ("*/5 * * * *", _at(minute=15)),
        ("0 9 * * *", _at(hour=9, minute=0)),
        ("0 9 30 7 *", _at(day=30)),
        ("0 9 * * 4", _at()),
        ("0 9 * * 0,4,6", _at()),
        ("0 9 * 6-8 *", _at(month=7)),
    ],
)
def test_parser_matches_each_supported_safe_field_form(source: str, timestamp: datetime) -> None:
    expression = parse_cron_expression(source)

    assert expression.source == source
    assert cron_matches(expression, timestamp) is True


def test_day_of_month_and_day_of_week_use_or_when_both_are_constrained() -> None:
    expression = parse_cron_expression("0 9 31 7 4")

    assert cron_matches(expression, _at(day=30)) is True
    assert cron_matches(expression, _at(day=31)) is True
    assert cron_matches(expression, _at(day=29)) is False


def test_literal_star_is_the_only_unconstrained_dom_or_dow_form() -> None:
    expression = parse_cron_expression("0 9 */1 7 4")

    assert expression.day_of_month.is_unconstrained is False
    assert expression.day_of_week.is_unconstrained is False
    # */1 覆盖所有日期，但它仍是语法上受限的字段；Scheduler 可据此保留标准 OR 语义。
    assert cron_matches(expression, _at(day=29)) is True
    assert cron_matches(expression, _at(day=30)) is True


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("* * * *", "恰好包含五个字段"),
        ("* * * * * *", "恰好包含五个字段"),
        ("60 * * * *", "字段“分钟”"),
        ("* 24 * * *", "字段“小时”"),
        ("* * 0 * *", "字段“日”"),
        ("* * * 13 *", "字段“月”"),
        ("* * * * 7", "字段“星期”"),
        ("*/0 * * * *", "步长超出允许范围"),
        ("1-5/2 * * * *", "必须是十进制整数"),
        ("1,2-3 * * * *", "必须是十进制整数"),
        ("? * * * *", "必须是十进制整数"),
        ("JAN * * * *", "必须是十进制整数"),
    ],
)
def test_parser_rejects_everything_outside_the_safe_subset(
    source: str,
    message: str,
) -> None:
    with pytest.raises(CronExpressionValidationError, match=message):
        parse_cron_expression(source)


def test_matcher_rejects_naive_datetime_and_unparsed_expression() -> None:
    expression = parse_cron_expression("* * * * *")

    with pytest.raises(ValueError, match="带时区"):
        cron_matches(expression, datetime(2026, 7, 30, 9, 0))
    with pytest.raises(TypeError, match="CronExpression"):
        cron_matches("* * * * *", _at())  # type: ignore[arg-type]
