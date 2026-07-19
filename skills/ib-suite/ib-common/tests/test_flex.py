"""Tests for shared IBKR Flex date, token, and query-window helpers."""

from datetime import date

import pytest

from ib_common.config import Config
from ib_common.flex import (
    parse_iso_date,
    resolve_date_range,
    resolve_flex_token,
    select_flex_window,
    select_numeric_window,
)


def test_select_numeric_window_returns_smallest_covering_key() -> None:
    """The smallest configured window that covers the range is selected."""
    assert select_numeric_window(
        {"7": "q7", "30": "q30", "365": "q365"},
        date(2026, 7, 1), date(2026, 7, 19), allow_partial=False,
    ) == ("30", "q30", None)


def test_select_numeric_window_can_require_complete_coverage() -> None:
    """Complete-coverage callers receive an actionable error for a gap."""
    with pytest.raises(ValueError, match="365 days"):
        select_numeric_window(
            {"30": "q30"}, date(2025, 7, 20), date(2026, 7, 19),
            allow_partial=False,
        )


def test_resolve_date_range_is_inclusive_and_ordered() -> None:
    """Explicit date bounds retain inclusive ordering semantics."""
    assert resolve_date_range(
        "2026-07-01", "2026-07-19", date(2026, 7, 19)
    ) == (date(2026, 7, 1), date(2026, 7, 19))
    with pytest.raises(ValueError, match="on or before"):
        resolve_date_range("2026-07-20", "2026-07-19", date(2026, 7, 19))


def test_resolve_flex_token_never_includes_value_in_error() -> None:
    """Missing Flex token errors are actionable without exposing a value."""
    with pytest.raises(ValueError, match="--token-stdin") as excinfo:
        resolve_flex_token(Config())

    assert "configure_flex.py --token " not in str(excinfo.value)


def test_select_flex_window_uses_smallest_calendar_period_covering_range() -> None:
    """Registered MTD/YTD windows participate by their actual calendar span."""
    query_ids = {
        "7": "q7",
        "30": "q30",
        "365": "q365",
        "mtd": "qmtd",
        "ytd": "qytd",
    }

    assert select_flex_window(
        query_ids,
        date(2026, 7, 10),
        date(2026, 7, 19),
        allow_partial=False,
    ) == ("mtd", "qmtd", None)
    assert select_flex_window(
        query_ids,
        date(2026, 1, 1),
        date(2026, 7, 19),
        allow_partial=False,
    ) == ("ytd", "qytd", None)
    assert select_flex_window(
        query_ids,
        date(2025, 7, 20),
        date(2026, 7, 19),
        allow_partial=False,
    ) == ("365", "q365", None)


def test_select_flex_window_period_only_map_fails_when_history_is_uncovered() -> None:
    """A calendar-period query cannot claim coverage before its period start."""
    with pytest.raises(ValueError, match="requires 365 days"):
        select_flex_window(
            {"mtd": "qmtd", "ytd": "qytd"},
            date(2025, 7, 20),
            date(2026, 7, 19),
            allow_partial=False,
        )
