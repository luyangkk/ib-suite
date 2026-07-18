from pathlib import Path
import importlib.util

import pytest

SPEC = Path(__file__).parent.parent / "scripts" / "flex_fetch.py"
spec = importlib.util.spec_from_file_location("flex_fetch", SPEC)
flex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flex)

FIX = Path(__file__).parent / "fixtures"


def test_parse_flex_dividends():
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    divs = flex.parse_flex_dividends(xml_text)
    assert len(divs) == 1
    assert divs[0].symbol == "AAPL"
    assert divs[0].gross == 24.0
    assert divs[0].currency == "USD"


def test_parse_flex_trades():
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    trades = flex.parse_flex_trades(xml_text)
    assert len(trades) == 2
    assert trades[0].symbol == "AAPL"
    assert trades[0].side == "BUY"
    assert trades[0].quantity == 100.0


def test_parse_flex_trade_records_keeps_required_trade_history_fields():
    """The extended parser exposes each Flex fill without changing Execution."""
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    rows = flex.parse_flex_trade_records(xml_text)

    assert len(rows) == 2
    row = rows[0]
    assert row.exec_id == "T1"
    assert row.ts.isoformat() == "2026-02-01T15:30:00+00:00"
    assert row.commission_currency == "USD"
    assert row.order_type == "LMT"
    assert row.exchange == "NASDAQ"
    assert row.open_close == "O"
    assert row.realized_pnl == 0.0
    assert row.fx_rate_to_base == 1.0
    assert row.multiplier == 1.0

    option = rows[1]
    assert option.exec_id == "OPT1"
    assert option.multiplier == 100.0
    assert option.notional == 200.0


def test_parse_flex_trade_records_rejects_non_positive_multiplier():
    """Flex multipliers must be positive when a contract supplies one."""
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="greater than 0"):
        flex.parse_flex_trade_records(xml_text.replace('multiplier="100"', 'multiplier="0"'))


def test_fetch_flex_report_two_step_handshake():
    class FakeResp:
        def __init__(self, text): self.text = text; self.status_code = 200
        def raise_for_status(self): pass

    calls = []
    def fake_get(url, params=None, **kw):
        calls.append((url, params))
        if "SendRequest" in url:
            return FakeResp("<FlexStatementResponse><Status>Success</Status>"
                            "<ReferenceCode>REF123</ReferenceCode>"
                            "<Url>https://x/GetStatement</Url></FlexStatementResponse>")
        return FakeResp("<FlexQueryResponse>OK</FlexQueryResponse>")

    out = flex.fetch_flex_report("TOK", "Q1", http_get=fake_get)
    assert "FlexQueryResponse" in out
    assert len(calls) == 2                       # SendRequest then GetStatement
