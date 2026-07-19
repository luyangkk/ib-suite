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


def test_parse_flex_trade_records_accepts_present_empty_order_type():
    """IBKR assignment rows may carry an explicitly empty orderType."""
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    xml_text = xml_text.replace('orderType="LMT"', 'orderType=""', 1)

    rows = flex.parse_flex_trade_records(xml_text)

    assert rows[0].order_type == ""


def test_parse_flex_trade_records_rejects_absent_order_type():
    """Omitting orderType from the query remains an actionable error."""
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")
    xml_text = xml_text.replace(' orderType="LMT"', "", 1)

    with pytest.raises(ValueError, match="orderType.*Flex Query Trades"):
        flex.parse_flex_trade_records(xml_text)


def test_parse_flex_trade_records_rejects_non_positive_multiplier():
    """Flex multipliers must be positive when a contract supplies one."""
    xml_text = (FIX / "flex_response_sample.xml").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="greater than 0"):
        flex.parse_flex_trade_records(xml_text.replace('multiplier="100"', 'multiplier="0"'))


@pytest.mark.parametrize("url_tag", ["url", "Url"])
def test_fetch_flex_report_uses_current_endpoint_headers_and_response_url(url_tag):
    class FakeResp:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

        def raise_for_status(self):
            pass

    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params, kwargs))
        if "SendRequest" in url:
            return FakeResp(
                "<FlexStatementResponse><Status>Success</Status>"
                "<ReferenceCode>REF123</ReferenceCode>"
                f"<{url_tag}>https://reports.example/GetStatement</{url_tag}>"
                "</FlexStatementResponse>"
            )
        return FakeResp("<FlexQueryResponse>OK</FlexQueryResponse>")

    out = flex.fetch_flex_report("TOK", "Q1", http_get=fake_get)

    assert "FlexQueryResponse" in out
    assert calls[0][0] == (
        "https://ndcdyn.interactivebrokers.com/AccountManagement/"
        "FlexWebService/SendRequest"
    )
    assert calls[1][0] == "https://reports.example/GetStatement"
    assert all(
        call[2]["headers"]["User-Agent"] == "Python/3 ib-suite/0.1"
        for call in calls
    )


def test_fetch_flex_report_raises_sanitized_ibkr_error():
    class FakeResp:
        text = (
            "<FlexStatementResponse><Status>Fail</Status>"
            "<ErrorCode>1014</ErrorCode>"
            "<ErrorMessage>Query secret-query is invalid; "
            "see https://example.test/?t=secret-token&amp;q=secret-query</ErrorMessage>"
            "<RawSecret>token-and-query-must-not-leak</RawSecret>"
            "</FlexStatementResponse>"
        )
        status_code = 200

        def raise_for_status(self):
            pass

    with pytest.raises(flex.FlexServiceError) as excinfo:
        flex.fetch_flex_report(
            "secret-token",
            "secret-query",
            http_get=lambda *_args, **_kwargs: FakeResp(),
        )

    assert str(excinfo.value).startswith("IBKR Flex error 1014:")
    assert "secret-token" not in str(excinfo.value)
    assert "secret-query" not in str(excinfo.value)
    assert "https://" not in str(excinfo.value)
    assert "token-and-query-must-not-leak" not in str(excinfo.value)


def test_fetch_flex_report_redacts_get_statement_error_secrets():
    class FakeResp:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

        def raise_for_status(self):
            pass

    def fake_get(url, params=None, **_kwargs):
        if "SendRequest" in url:
            return FakeResp(
                "<FlexStatementResponse><Status>Success</Status>"
                "<ReferenceCode>secret-reference</ReferenceCode>"
                "<url>https://reports.example/GetStatement</url>"
                "</FlexStatementResponse>"
            )
        return FakeResp(
            "<FlexStatementResponse><Status>Fail</Status>"
            "<ErrorCode>1017</ErrorCode>"
            "<ErrorMessage>Reference secret-reference failed for secret-query "
            "with secret-token at https://example.test/report</ErrorMessage>"
            "</FlexStatementResponse>"
        )

    with pytest.raises(flex.FlexServiceError) as excinfo:
        flex.fetch_flex_report(
            "secret-token", "secret-query", http_get=fake_get
        )

    message = str(excinfo.value)
    assert message.startswith("IBKR Flex error 1017:")
    assert "secret-token" not in message
    assert "secret-query" not in message
    assert "secret-reference" not in message
    assert "https://" not in message


def test_fetch_flex_report_raises_when_generation_polling_is_exhausted():
    class FakeResp:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

        def raise_for_status(self):
            pass

    calls = 0

    def fake_get(url, params=None, **_kwargs):
        nonlocal calls
        calls += 1
        if "SendRequest" in url:
            return FakeResp(
                "<FlexStatementResponse><Status>Success</Status>"
                "<ReferenceCode>REF123</ReferenceCode>"
                "</FlexStatementResponse>"
            )
        return FakeResp(
            "<FlexStatementResponse><Status>Fail</Status>"
            "<ErrorCode>1019</ErrorCode>"
            "<ErrorMessage>Statement generation in progress.</ErrorMessage>"
            "</FlexStatementResponse>"
        )

    with pytest.raises(flex.FlexServiceError, match="1019"):
        flex.fetch_flex_report(
            "token",
            "query",
            http_get=fake_get,
            poll_interval=0,
            max_polls=2,
        )

    assert calls == 3
