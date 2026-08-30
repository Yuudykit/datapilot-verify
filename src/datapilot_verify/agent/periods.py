"""环比期间解析（BUG-017）。

此前对比期间硬编码为 2026-07 vs 2026-06，问题里提到的任何月份都被忽略。
这里的解析顺序：问题中明确提到的月份优先（提到两个月时较后者为本期）；
未提到月份时取数据里 `paid_at` 的最新月份；两者都拿不到时返回 None，
由调用方决定兜底行为。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

MonthPeriod = tuple[tuple[int, int], tuple[int, int]]

_MONTH_PATTERN = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月")
_FALLBACK_YEAR = 2026  # 与内置样例数据一致的最终兜底年份


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def mentioned_months(question: str) -> list[tuple[int | None, int]]:
    """按出现顺序返回问题里提到的 (年, 月)；年份未写明时为 None。"""
    results: list[tuple[int | None, int]] = []
    for match in _MONTH_PATTERN.finditer(question):
        year = int(match.group(1)) if match.group(1) else None
        month = int(match.group(2))
        if 1 <= month <= 12:
            results.append((year, month))
    return results


def resolve_comparison_periods(
    question: str, data_end: date | None
) -> MonthPeriod | None:
    """返回 ((本期年, 本期月), (上期年, 上期月))；无法确定时返回 None。"""
    mentions = mentioned_months(question)
    if mentions:
        default_year = data_end.year if data_end else _FALLBACK_YEAR
        resolved = sorted(
            {(year if year else default_year, month) for year, month in mentions}
        )
        if len(resolved) >= 2:
            previous, current = resolved[-2], resolved[-1]
        else:
            current = resolved[0]
            previous = _previous_month(*current)
    elif data_end is not None:
        current = (data_end.year, data_end.month)
        previous = _previous_month(*current)
    else:
        return None
    if current <= previous:
        return None
    return ((current[0], current[1]), previous)


def to_comparison_dates(periods: tuple[MonthPeriod, MonthPeriod]) -> tuple[
    tuple[date, date], tuple[date, date]
]:
    """把 ((年, 月), (年, 月)) 端点转成 (期初, 期末) 日期区间。"""
    (cy, cm), (py, pm) = periods
    current = (date(cy, cm, 1), _month_end(cy, cm))
    previous = (date(py, pm, 1), _month_end(py, pm))
    return current, previous


def month_label(year: int, month: int) -> str:
    return f"{year}年{month}月"


def latest_paid_date(orders_csv: Path) -> date | None:
    """读取订单数据里 `paid_at` 的最大日期；文件缺失或不可解析时返回 None。"""
    try:
        import pandas as pd

        frame = pd.read_csv(orders_csv, usecols=["paid_at"])
        parsed = pd.to_datetime(frame["paid_at"], errors="coerce").dropna()
    except Exception:  # 数据缺失/表头不符时不阻断分析，交由调用方兜底
        return None
    if parsed.empty:
        return None
    return parsed.max().date()
