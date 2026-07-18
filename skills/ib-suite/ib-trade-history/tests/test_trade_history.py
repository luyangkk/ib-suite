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


def test_config_credentials_override_complete_environment_pair(tmp_path):
    """A complete local Flex pair takes precedence over shell credentials."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: config-token\n  query_id: config-query\n",
        encoding="utf-8",
    )

    assert trade_history.resolve_flex_credentials(
        load_config(config),
        {"FLEX_TOKEN": "env-token", "FLEX_QUERY_ID": "env-query"},
    ) == ("config-token", "config-query")


def test_partial_config_credentials_are_rejected(tmp_path):
    """A Flex credential pair must come wholly from local configuration."""
    config = tmp_path / "config.yaml"
    config.write_text("flex:\n  token: only-token\n  query_id: null\n", encoding="utf-8")

    with pytest.raises(ValueError, match="config.flex"):
        trade_history.resolve_flex_credentials(load_config(config), {})


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
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
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
        environ={"FLEX_TOKEN": "test-token", "FLEX_QUERY_ID": "test-query"},
    )

    assert calls == [("test-token", "test-query")]
    assert out["start_date"] == "2026-07-05"
    assert out["end_date"] == "2026-07-11"
    assert [row["exec_id"] for row in out["trades"]] == ["B1", "S1", "S2", "OLD1"]


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
            environ={"FLEX_TOKEN": "x", "FLEX_QUERY_ID": "y"},
        )

    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Flex credentials are not configured"):
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse/>",
            environ={},
        )


def test_skill_metadata_and_source_preserve_read_only_boundary():
    """The skill is discoverable, has exact runnable paths, and no order path."""
    skill = (Path(__file__).parent.parent / "SKILL.md").read_text(encoding="utf-8")
    source = SPEC.read_text(encoding="utf-8")
    assert "name: ib-trade-history" in skill
    assert "Read-only" in skill
    assert "{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py" in skill
    assert "FLEX_TOKEN" in skill and "FLEX_QUERY_ID" in skill
    assert "env: [FLEX_TOKEN, FLEX_QUERY_ID]" not in skill
    assert (
        "{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py" in skill
    )
    assert "never echoes values" in skill
    assert "does not validate against the Flex Web Service" in skill
    assert "ibCommissionCurrency" in skill
    assert "multiplier" in skill
    assert "third currency" in skill
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in source


def test_skill_guides_safe_partial_flex_credential_recovery():
    """Partial local credentials require explicit replacement, unlike an empty config."""
    skill = (Path(__file__).parent.parent / "SKILL.md").read_text(encoding="utf-8")
    configure = (
        "{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \\\n"
        "  --config .ib-suite/config.yaml --token '<provided-token>' "
        "--query-id '<provided-query-id>'"
    )

    assert "When neither field is present" in skill
    assert configure in skill
    assert "When exactly one field is present" in skill
    assert f"{configure} \\\n  --force" in skill


def test_orchestration_redacts_request_exception_secrets(tmp_path):
    """Request failure tracebacks never expose Flex credentials or response text."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    token, query_id = "test-token", "test-query"
    url = f"https://example/?t={token}&q={query_id}&body=secret-body"

    def failed_fetch(_: str, __: str) -> str:
        raise requests.RequestException(f"GET {url} failed")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=failed_fetch,
            environ={"FLEX_TOKEN": token, "FLEX_QUERY_ID": query_id},
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


def test_orchestration_redacts_parse_error_from_flex_fetcher(tmp_path):
    """Malformed Flex handshake XML is mapped without exposing parser details."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")

    def failed_fetch(_: str, __: str) -> str:
        raise ET.ParseError("malformed handshake response")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=failed_fetch,
            environ={"FLEX_TOKEN": "x", "FLEX_QUERY_ID": "y"},
        )

    assert "Flex report retrieval failed" in str(excinfo.value)
    assert "malformed handshake response" not in str(excinfo.value)


def test_orchestration_redacts_value_error_from_flex_fetcher(tmp_path):
    """Fetcher ValueErrors cannot expose Flex URLs or credentials."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    token, query_id = "value-token", "value-query"
    url = f"https://example.test/?t={token}&q={query_id}&body=secret-body"

    def failed_fetch(_: str, __: str) -> str:
        raise ValueError(f"GET {url} failed")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=failed_fetch,
            environ={"FLEX_TOKEN": token, "FLEX_QUERY_ID": query_id},
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
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tradeID.*Flex Query Trades"):
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<FlexQueryResponse><Trade/></FlexQueryResponse>",
            environ={"FLEX_TOKEN": "x", "FLEX_QUERY_ID": "y"},
        )


def test_orchestration_rejects_invalid_flex_xml_without_parser_details(tmp_path):
    """Malformed Flex output receives a safe, actionable public error."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        trade_history.trade_history(
            str(config),
            "2026-07-09",
            "2026-07-11",
            fetcher=lambda *_: "<html>service failure",
            environ={"FLEX_TOKEN": "x", "FLEX_QUERY_ID": "y"},
        )

    assert str(excinfo.value) == (
        "Flex response is not a valid report; check the Flex Query and service status"
    )


def test_main_prints_one_json_line_on_success(monkeypatch, capsys):
    """The CLI emits exactly one JSON object and no stderr on success."""
    expected = {"trades": [], "summary": {}}
    monkeypatch.setattr(trade_history, "trade_history", lambda *_: expected)
    monkeypatch.setattr(sys, "argv", ["trade_history.py", "--config", "config.yaml"])

    trade_history.main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == expected


def test_main_redacts_request_exception_secrets(monkeypatch, capsys, tmp_path):
    """The CLI displays only the safe request-failure message."""
    config = tmp_path / "config.yaml"
    config.write_text("data:\n  base_currency: USD\n", encoding="utf-8")
    token, query_id = "cli-token-for-redaction", "cli-query-for-redaction"

    def failed_fetch(_: str, __: str) -> str:
        raise requests.RequestException(
            f"GET https://example.test/?t={token}&q={query_id} failed"
        )

    monkeypatch.setattr(
        trade_history.trade_history, "__defaults__", (failed_fetch, None, None)
    )
    monkeypatch.setenv("FLEX_TOKEN", token)
    monkeypatch.setenv("FLEX_QUERY_ID", query_id)
    monkeypatch.setattr(sys, "argv", ["trade_history.py", "--config", str(config)])

    with pytest.raises(SystemExit) as excinfo:
        trade_history.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert captured.out == ""
    assert "Flex report retrieval failed" in captured.err
    assert token not in captured.err
    assert query_id not in captured.err
