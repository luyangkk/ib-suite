from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import traceback
import xml.etree.ElementTree as ET

import pytest
import requests
from ib_common.config import load_config


SPEC = Path(__file__).parent.parent / "scripts" / "trade_history.py"
spec = importlib.util.spec_from_file_location("trade_history", SPEC)
trade_history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trade_history)


def test_resolve_flex_token_reads_config(tmp_path):
    """The Flex token is read solely from local configuration."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: config-token\n"
        "  trade_history_query_ids:\n    7: q7\n",
        encoding="utf-8",
    )
    assert trade_history.resolve_flex_token(load_config(config)) == "config-token"


def test_resolve_flex_token_missing_is_actionable(tmp_path):
    """A missing token points the operator at configure_flex.py."""
    config = tmp_path / "config.yaml"
    config.write_text("flex:\n  trade_history_query_ids:\n    7: q7\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Flex token"):
        trade_history.resolve_flex_token(load_config(config))


def test_build_report_filters_inclusively_and_aggregates_base_currency():
    """Every in-range fill survives and only Flex FX-converted money is summed."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)

    report = trade_history.build_report(
        rows, date(2026, 7, 9), date(2026, 7, 11), "USD"
    )

    assert [row.exec_id for row in report.trades] == ["B1", "S1", "S2"]
    assert report.summary.total_trades == 3
    assert report.summary.buy_count == 1
    assert report.summary.sell_count == 2
    assert report.summary.total_notional == 5200.0
    assert report.summary.total_commission == 6.0
    assert report.trades[2].commission_currency == "USD"
    assert report.trades[2].base_commission == 4.0
    assert report.summary.profitable_trades == 1
    assert report.summary.losing_trades == 1
    assert report.summary.win_rate == 0.5
    assert report.summary.average_profit == 200.0
    assert report.summary.average_loss == -75.0
    assert report.summary.profit_loss_ratio == pytest.approx(200.0 / 75.0)


def test_build_report_rejects_missing_foreign_exchange_rate():
    """A mixed-currency total cannot silently assume an FX conversion."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)
    rows[2].fx_rate_to_base = None

    with pytest.raises(ValueError, match="fxRateToBase.*SGD"):
        trade_history.build_report(rows, date(2026, 7, 9), date(2026, 7, 11), "USD")


@pytest.mark.parametrize(
    ("rate", "label"),
    [
        (0.0, "zero"),
        (-0.75, "negative"),
        (float("nan"), "nan"),
        (float("inf"), "infinity"),
    ],
)
def test_build_report_rejects_nonpositive_or_nonfinite_foreign_exchange_rate(
    rate: float, label: str
):
    """Foreign-currency totals require a finite, positive Flex conversion rate."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)
    rows[2].fx_rate_to_base = rate

    with pytest.raises(ValueError, match="fxRateToBase.*SGD"):
        trade_history.build_report(rows, date(2026, 7, 9), date(2026, 7, 11), "USD")


def test_build_report_normalizes_base_currency_exchange_rate():
    """Base-currency trades always use one as their conversion rate."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)
    rows[0].fx_rate_to_base = float("nan")

    report = trade_history.build_report(rows, date(2026, 7, 9), date(2026, 7, 11), "USD")

    assert report.trades[0].fx_rate_to_base == 1.0


def test_summarize_rejects_missing_foreign_exchange_rate():
    """A direct summary cannot silently omit an unconverted foreign-currency fill."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)
    rows[2].fx_rate_to_base = None

    with pytest.raises(ValueError, match="S2.*fxRateToBase.*SGD"):
        trade_history.summarize(rows)


def test_parse_flex_trade_records_allows_empty_open_close_for_cash_trade():
    """CASH and IDEALFX-style fills can omit an open/close classification."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()

    cash_trade = trade_history.parse_flex_trade_records(xml)[3]

    assert cash_trade.exchange == "IDEALPRO"
    assert cash_trade.open_close == ""


def test_build_report_rejects_unconverted_third_currency_commission():
    """A commission cannot reuse an unrelated asset FX conversion rate."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    rows = trade_history.parse_flex_trade_records(xml)
    rows[2].commission_currency = "EUR"

    with pytest.raises(ValueError, match="S2.*commission currency.*EUR"):
        trade_history.build_report(rows, date(2026, 7, 9), date(2026, 7, 11), "USD")


def test_orchestration_uses_injected_flex_fetcher_and_default_period(tmp_path):
    """The executable fetches once, defaults to seven days, and emits JSON-safe data."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: test-token\n"
        "  trade_history_query_ids:\n    7: test-query\n",
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(token: str, query_id: str) -> str:
        calls.append((token, query_id))
        return xml

    out = trade_history.trade_history(
        str(config),
        None,
        None,
        fetcher=fake_fetch,
        today=date(2026, 7, 11),
    )

    assert calls == [("test-token", "test-query")]
    assert out["start_date"] == "2026-07-05"
    assert out["end_date"] == "2026-07-11"
    assert [row["exec_id"] for row in out["trades"]] == ["B1", "S1", "S2", "OLD1"]


def test_orchestration_selects_window_query_id_and_clips(tmp_path):
    """Orchestration fetches with the selected window's query_id then clips."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n"
        "  trade_history_query_ids:\n    7: q7\n    30: q30\n",
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(token: str, query_id: str) -> str:
        calls.append((token, query_id))
        return xml

    out = trade_history.trade_history(
        str(config), None, None, fetcher=fake_fetch, today=date(2026, 7, 11)
    )
    assert calls == [("t", "q7")]
    assert out["start_date"] == "2026-07-05"
    assert out["coverage_note"] is None


def test_orchestration_flags_coverage_gap(tmp_path):
    """A request beyond the largest window surfaces a coverage note."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n  trade_history_query_ids:\n    7: q7\n",
        encoding="utf-8",
    )
    out = trade_history.trade_history(
        str(config), "2026-01-01", "2026-07-11",
        fetcher=lambda *_: xml, today=date(2026, 7, 11),
    )
    assert out["coverage_note"] is not None


def test_orchestration_requires_base_currency_and_flex_environment(tmp_path):
    """The failure tells operators exactly which local setup is incomplete."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: null\n", encoding="utf-8")

    with pytest.raises(ValueError, match="data.base_currency"):
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse/>",
        )

    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Flex token"):
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse/>",
        )


def test_skill_metadata_and_source_preserve_read_only_boundary():
    """The skill is discoverable, has exact runnable paths, and no order path."""
    skill = (
        Path(__file__).resolve().parents[2] / "references" / "ib-trade-history.md"
    ).read_text(encoding="utf-8")
    source = SPEC.read_text(encoding="utf-8")
    assert "Read only" in skill
    assert "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" in skill
    assert "$SKILL_ROOT/ib-trade-history/scripts/trade_history.py" in skill
    assert "--window" in skill
    assert "--period" in skill
    assert "ytd" in skill
    assert "query_ids" in skill
    assert "$SKILL_ROOT/ib-trade-history/scripts/configure_flex.py" in skill
    assert "never echoes values" in skill
    assert "does not validate against the Flex Web Service" in skill
    assert "ibCommissionCurrency" in skill
    assert "multiplier" in skill
    assert "third currency" in skill
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in source


def test_skill_guides_window_registration_and_force_replacement():
    """The skill shows how to register windows and force replacements."""
    skill = (
        Path(__file__).parents[2] / "references" / "ib-trade-history.md"
    ).read_text(encoding="utf-8")
    assert "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" in skill
    assert "$SKILL_ROOT/ib-trade-history/scripts/configure_flex.py" in skill
    assert "--config $WORKSPACE_ROOT/.ib-suite/config.yaml" in skill
    assert "--token-stdin" in skill
    assert "--target trade_history" in skill
    assert "--window '7=<query-id>'" in skill
    assert "--token '<provided-token>'" not in skill
    assert "--force" in skill
    assert "smallest configured window" in skill


def test_orchestration_redacts_request_exception_secrets(tmp_path):
    """Request failure tracebacks never expose Flex credentials or response text."""
    token, query_id = "test-token", "test-query"
    config = tmp_path / "config.yaml"
    config.write_text(
        f"data:\n  base_currency: USD\nflex:\n  token: {token}\n"
        f"  trade_history_query_ids:\n    7: {query_id}\n",
        encoding="utf-8",
    )
    url = f"https://example/?t={token}&q={query_id}&body=secret-body"

    def failed_fetch(_: str, __: str) -> str:
        raise requests.RequestException(f"GET {url} failed")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=failed_fetch,
        )

    message = str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.value))
    assert "Flex report retrieval failed" in message
    assert token not in message
    assert query_id not in message
    assert "Flex report retrieval failed" in formatted
    assert token not in formatted
    assert query_id not in formatted
    assert url not in formatted
    assert "secret-body" not in formatted


def test_orchestration_preserves_sanitized_ibkr_error(tmp_path):
    """Known Flex service codes stay actionable without leaking credentials."""
    token, query_id = "service-token", "service-query"
    config = tmp_path / "config.yaml"
    config.write_text(
        f"data:\n  base_currency: USD\nflex:\n  token: {token}\n"
        f"  trade_history_query_ids:\n    7: {query_id}\n",
        encoding="utf-8",
    )

    def failed_fetch(_: str, __: str) -> str:
        raise trade_history.FlexServiceError("1014", "Query is invalid.")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config), "2026-07-09", "2026-07-11", fetcher=failed_fetch
        )

    assert str(excinfo.value) == "IBKR Flex error 1014: Query is invalid."
    assert token not in str(excinfo.value)
    assert query_id not in str(excinfo.value)


def test_orchestration_redacts_parse_error_from_flex_fetcher(tmp_path):
    """Malformed Flex handshake XML is mapped without exposing parser details."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: x\n  trade_history_query_ids:\n    7: y\n",
        encoding="utf-8",
    )

    def failed_fetch(_: str, __: str) -> str:
        raise ET.ParseError("malformed handshake response")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=failed_fetch,
        )

    assert "Flex report retrieval failed" in str(excinfo.value)
    assert "malformed handshake response" not in str(excinfo.value)


def test_orchestration_redacts_value_error_from_flex_fetcher(tmp_path):
    """Fetcher ValueErrors cannot expose Flex URLs or credentials."""
    token, query_id = "value-token", "value-query"
    config = tmp_path / "config.yaml"
    config.write_text(
        f"data:\n  base_currency: USD\nflex:\n  token: {token}\n"
        f"  trade_history_query_ids:\n    7: {query_id}\n",
        encoding="utf-8",
    )
    url = f"https://example.test/?t={token}&q={query_id}&body=secret-body"

    def failed_fetch(_: str, __: str) -> str:
        raise ValueError(f"GET {url} failed")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=failed_fetch,
        )

    message = str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.value))
    assert message.startswith("Flex report retrieval failed")
    assert token not in message
    assert query_id not in message
    assert token not in formatted
    assert query_id not in formatted
    assert url not in formatted
    assert "secret-body" not in formatted


def test_orchestration_preserves_actionable_parser_value_error(tmp_path):
    """Required Flex fields still identify the query setting that must be fixed."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: x\n  trade_history_query_ids:\n    7: y\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="tradeID.*Flex Query Trades"):
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse><Trade/></FlexQueryResponse>",
        )


def test_orchestration_rejects_invalid_flex_xml_without_parser_details(tmp_path):
    """Malformed Flex output receives a safe, actionable public error."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: x\n  trade_history_query_ids:\n    7: y\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<html>service failure",
        )

    assert str(excinfo.value) == (
        "Flex response is not a valid report; check the Flex Query and service status"
    )


def test_main_prints_one_json_line_on_success(monkeypatch, capsys):
    """The CLI emits exactly one JSON object and no stderr on success."""
    expected = {"trades": [], "summary": {}}
    monkeypatch.setattr(trade_history, "trade_history", lambda *_, **__: expected)
    monkeypatch.setattr(sys, "argv", ["trade_history.py", "--config", "config.yaml"])

    trade_history.main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == expected


def test_main_redacts_request_exception_secrets(monkeypatch, capsys, tmp_path):
    """The CLI displays only the safe request-failure message."""
    token, query_id = "cli-token-for-redaction", "cli-query-for-redaction"
    config = tmp_path / "config.yaml"
    config.write_text(
        f"data:\n  base_currency: USD\nflex:\n  token: {token}\n"
        f"  trade_history_query_ids:\n    7: {query_id}\n",
        encoding="utf-8",
    )

    def failed_fetch(_: str, __: str) -> str:
        raise requests.RequestException(
            f"GET https://example.test/?t={token}&q={query_id} failed"
        )

    monkeypatch.setattr(
        trade_history.trade_history, "__defaults__", (failed_fetch, None, None)
    )
    monkeypatch.setattr(sys, "argv", ["trade_history.py", "--config", str(config)])

    with pytest.raises(SystemExit) as excinfo:
        trade_history.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert captured.out == ""
    assert "Flex report retrieval failed" in captured.err
    assert token not in captured.err
    assert query_id not in captured.err


def test_select_flex_window_rounds_up_to_smallest_covering_window():
    """A 7-day gap picks the 7 window when 7 and 30 are configured."""
    days, query_id, note = trade_history.select_flex_window(
        {"7": "q7", "30": "q30"}, date(2026, 7, 12), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (7, "q7", None)


def test_select_flex_window_includes_today_in_gap():
    """Gap counts today inclusively, so same-day requests need at least 1 day."""
    days, query_id, note = trade_history.select_flex_window(
        {"1": "q1", "30": "q30"}, date(2026, 7, 18), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (1, "q1", None)


def test_select_flex_window_rounds_up_when_no_exact_match():
    """A 10-day gap with only 7 and 30 configured selects 30."""
    days, query_id, note = trade_history.select_flex_window(
        {"7": "q7", "30": "q30"}, date(2026, 7, 9), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (30, "q30", None)


def test_select_flex_window_falls_back_to_largest_with_note():
    """A request beyond the largest window uses it and flags possible gaps."""
    days, query_id, note = trade_history.select_flex_window(
        {"7": "q7", "30": "q30"}, date(2026, 1, 1), date(2026, 7, 18)
    )
    assert days == 30
    assert query_id == "q30"
    assert note is not None and "30" in note


def test_select_flex_window_ignores_period_keys():
    """Period keys never participate in numeric-day auto-selection."""
    days, query_id, note = trade_history.select_flex_window(
        {"7": "q7", "mtd": "qm", "ytd": "qy"}, date(2026, 7, 12), date(2026, 7, 18)
    )
    assert (days, query_id, note) == (7, "q7", None)


def test_select_flex_window_rejects_period_only_map():
    """A map with no numeric windows is an actionable configuration error."""
    with pytest.raises(ValueError, match="--window"):
        trade_history.select_flex_window(
            {"mtd": "qm"}, date(2026, 7, 12), date(2026, 7, 18)
        )


def test_select_flex_window_rejects_empty_map():
    """No configured windows is an actionable configuration error."""
    with pytest.raises(ValueError, match="--window"):
        trade_history.select_flex_window({}, date(2026, 7, 12), date(2026, 7, 18))


def test_resolve_period_bounds_mtd_starts_at_month_first():
    """Month-to-date spans the first of the month through today, inclusive."""
    assert trade_history.resolve_period_bounds("mtd", date(2026, 7, 19)) == (
        date(2026, 7, 1),
        date(2026, 7, 19),
    )


def test_resolve_period_bounds_ytd_starts_at_year_first():
    """Year-to-date spans January 1 through today, inclusive."""
    assert trade_history.resolve_period_bounds("ytd", date(2026, 7, 19)) == (
        date(2026, 1, 1),
        date(2026, 7, 19),
    )


def test_select_period_window_uses_registered_query_id():
    """A registered period key is used directly with no coverage note."""
    query_id, note = trade_history.select_period_window(
        {"7": "q7", "ytd": "qy"}, "ytd", date(2026, 7, 19)
    )
    assert (query_id, note) == ("qy", None)


def test_select_period_window_falls_back_to_numeric_pool_with_note():
    """An unregistered period falls back to the numeric pool and flags the gap."""
    query_id, note = trade_history.select_period_window(
        {"7": "q7"}, "ytd", date(2026, 7, 19)
    )
    assert query_id == "q7"
    assert note is not None and "30" not in note  # note is from select_flex_window


def test_orchestration_period_fetches_and_clips(tmp_path):
    """--period mtd fetches the period's query id and clips to month-to-date."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n"
        "  trade_history_query_ids:\n    7: q7\n    mtd: qm\n",
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(token: str, query_id: str) -> str:
        calls.append((token, query_id))
        return xml

    out = trade_history.trade_history(
        str(config), None, None, fetcher=fake_fetch,
        today=date(2026, 7, 11), period="mtd",
    )
    assert calls == [("t", "qm")]
    assert out["start_date"] == "2026-07-01"
    assert out["end_date"] == "2026-07-11"
    assert out["coverage_note"] is None


def test_orchestration_period_rejects_explicit_dates(tmp_path):
    """--period cannot be combined with explicit start/end dates."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n  trade_history_query_ids:\n    mtd: qm\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        trade_history.trade_history(
            str(config), "2026-07-01", "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse/>",
            today=date(2026, 7, 11), period="mtd",
        )


def test_orchestration_period_redacts_fetch_failure(tmp_path):
    """On the period path, a fetch failure leaks neither token nor query id."""
    token, query_id = "period-token", "period-query"
    config = tmp_path / "config.yaml"
    config.write_text(
        f"data:\n  base_currency: USD\nflex:\n  token: {token}\n"
        f"  trade_history_query_ids:\n    ytd: {query_id}\n",
        encoding="utf-8",
    )

    def failed_fetch(_: str, __: str) -> str:
        raise requests.RequestException(f"GET ?q={query_id} failed")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config), None, None, fetcher=failed_fetch,
            today=date(2026, 7, 19), period="ytd",
        )
    message = str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.value))
    assert "Flex report retrieval failed" in message
    assert token not in formatted and query_id not in formatted
