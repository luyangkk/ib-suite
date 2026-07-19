"""Shared IBKR Flex date, token, and query-window helpers."""
from __future__ import annotations

from datetime import date, timedelta

from ib_common.config import Config


def parse_iso_date(value: str) -> date:
    """Parse an ISO calendar date or raise an actionable argument error."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def resolve_date_range(
    start: str | None,
    end: str | None,
    today: date,
    default_days: int = 7,
) -> tuple[date, date]:
    """Resolve explicit inclusive bounds or a default inclusive date range."""
    if (start is None) != (end is None):
        raise ValueError("--start-date and --end-date must be supplied together")
    if start is None:
        return today - timedelta(days=default_days - 1), today
    start_date, end_date = parse_iso_date(start), parse_iso_date(end)
    if start_date > end_date:
        raise ValueError("--start-date must be on or before --end-date")
    return start_date, end_date


def resolve_flex_token(cfg: Config) -> str:
    """Return the Flex token from local configuration or raise actionably."""
    if cfg.flex.token:
        return cfg.flex.token
    raise ValueError(
        "Flex token is not configured; run configure_flex.py --token before querying"
    )


def select_numeric_window(
    query_ids: dict[str, str],
    required_start: date,
    today: date,
    *,
    allow_partial: bool,
) -> tuple[str, str, str | None]:
    """Select the smallest numeric Flex window covering an inclusive date span."""
    numeric = {int(key): value for key, value in query_ids.items() if key.isdigit()}
    if not numeric:
        raise ValueError(
            "no Flex windows configured; run configure_flex.py with --window"
        )
    gap = (today - required_start).days + 1
    covering = sorted(days for days in numeric if days >= gap)
    if covering:
        selected = covering[0]
        return str(selected), numeric[selected], None

    largest = max(numeric)
    note = (
        f"requested start date precedes the largest configured Flex window "
        f"({largest} days); results may be incomplete"
    )
    if allow_partial:
        return str(largest), numeric[largest], note
    raise ValueError(
        f"requested date range requires {gap} days, but the largest configured "
        f"Flex window is {largest} days; add a window with at least {gap} days"
    )
