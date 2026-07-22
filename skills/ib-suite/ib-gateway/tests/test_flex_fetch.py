from pathlib import Path
import importlib.util
import xml.etree.ElementTree as ET

import pytest
import requests

SPEC = Path(__file__).parent.parent / "scripts" / "flex_fetch.py"
spec = importlib.util.spec_from_file_location("flex_fetch", SPEC)
flex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flex)

FIX = Path(__file__).parent / "fixtures"
DIVIDEND_FIX = (
    Path(__file__).parents[2]
    / "ib-dividend-income"
    / "tests"
    / "fixtures"
    / "flex_dividend_income_sample.xml"
)


def _without_section(xml_text: str, section_name: str) -> str:
    """Return fixture XML with one statement-level section removed."""
    root = ET.fromstring(xml_text)
    statement = root.find(".//FlexStatement")
    assert statement is not None
    xml_section_name = (
        "SecuritiesInfo"
        if section_name == "FinancialInstrumentInformation"
        else section_name
    )
    section = statement.find(xml_section_name)
    assert section is not None
    statement.remove(section)
    return ET.tostring(root, encoding="unicode")


def _without_attribute(
    xml_text: str, element_name: str, attribute_name: str
) -> str:
    """Return fixture XML with one selected query attribute removed."""
    root = ET.fromstring(xml_text)
    element = root.find(f".//{element_name}")
    assert element is not None
    del element.attrib[attribute_name]
    return ET.tostring(root, encoding="unicode")


def _with_blank_attribute(
    xml_text: str, element_name: str, attribute_name: str
) -> str:
    """Return fixture XML with one selected query attribute blanked."""
    root = ET.fromstring(xml_text)
    element = root.find(f".//{element_name}")
    assert element is not None
    element.set(attribute_name, "")
    return ET.tostring(root, encoding="unicode")


def test_parse_flex_dividend_dataset_keeps_normalized_raw_records() -> None:
    """The six dividend sections become typed records without sign changes."""
    xml_text = DIVIDEND_FIX.read_text(encoding="utf-8")

    dataset = flex.parse_flex_dividend_dataset(xml_text)

    assert dataset.base_currency == "USD"
    assert dataset.statement_from_date.isoformat() == "2026-01-01"
    assert dataset.statement_to_date.isoformat() == "2026-07-31"
    assert len(dataset.cash_transactions) == 2
    assert dataset.cash_transactions[0].symbol == "AAPL"
    assert dataset.cash_transactions[0].fx_rate_to_base == 1.0
    assert dataset.cash_transactions[0].ts.isoformat() == (
        "2026-05-15T08:30:00+00:00"
    )
    assert dataset.cash_transactions[1].amount == -3.75
    assert dataset.cash_transactions[0].underlying_conid is None
    assert dataset.dividend_accruals[0].quantity == 100
    assert dataset.dividend_accruals[1].gross_amount == -25.0
    assert dataset.dividend_accruals[1].code == "RE"
    assert dataset.open_dividend_accruals[0].pay_date.isoformat() == "2026-08-15"
    assert dataset.open_positions[0].level_of_detail == "SUMMARY"
    assert dataset.open_positions[2].side == "SHORT"
    assert dataset.instruments[0].listing_exchange == "NASDAQ"
    assert dataset.instruments[3].listing_exchange is None


@pytest.mark.parametrize(
    ("attribute_name", "model_field"),
    [("date", "accrual_date"), ("reportDate", "report_date")],
)
def test_blank_optional_dividend_accrual_dates_become_none(
    attribute_name: str, model_field: str
) -> None:
    """Selected blank nullable accrual dates remain present facts with no value."""
    xml_text = DIVIDEND_FIX.read_text(encoding="utf-8")
    xml_text = _with_blank_attribute(
        xml_text, "ChangeInDividendAccrual", attribute_name
    )

    dataset = flex.parse_flex_dividend_dataset(xml_text)

    assert getattr(dataset.dividend_accruals[0], model_field) is None


@pytest.mark.parametrize(
    ("attribute_name", "model_field"),
    [("assetCategory", "asset_class"), ("symbol", "symbol")],
)
def test_blank_cash_security_fields_are_tolerated_for_withholding_rows(
    attribute_name: str, model_field: str
) -> None:
    """IBKR emits blank assetCategory/symbol on withholding-tax cash rows."""
    xml_text = DIVIDEND_FIX.read_text(encoding="utf-8")
    xml_text = _with_blank_attribute(xml_text, "CashTransaction", attribute_name)

    dataset = flex.parse_flex_dividend_dataset(xml_text)

    assert getattr(dataset.cash_transactions[0], model_field) == ""


def test_date_only_cash_datetime_is_parsed_as_midnight_utc() -> None:
    """IBKR reports date-only dateTime on withholding rows; treat it as midnight."""
    root = ET.fromstring(DIVIDEND_FIX.read_text(encoding="utf-8"))
    element = root.find(".//CashTransaction")
    assert element is not None
    element.set("dateTime", "20260515")
    xml_text = ET.tostring(root, encoding="unicode")

    dataset = flex.parse_flex_dividend_dataset(xml_text)

    assert dataset.cash_transactions[0].ts.isoformat() == (
        "2026-05-15T00:00:00+00:00"
    )


def test_parse_flex_dividend_dataset_accepts_legacy_instrument_tags() -> None:
    """Legacy fixture aliases remain compatible with real SecuritiesInfo tags."""
    xml_text = DIVIDEND_FIX.read_text(encoding="utf-8")
    xml_text = xml_text.replace("SecuritiesInfo", "FinancialInstrumentInformation")
    xml_text = xml_text.replace("SecurityInfo", "FinancialInstrumentInfo")

    dataset = flex.parse_flex_dividend_dataset(xml_text)

    assert dataset.instruments[0].symbol == "AAPL"


def test_unrelated_cash_transaction_with_blank_security_fields_is_ignored() -> None:
    """A benign deposit row cannot invalidate relevant dividend cash parsing."""
    root = ET.fromstring(DIVIDEND_FIX.read_text(encoding="utf-8"))
    section = root.find(".//CashTransactions")
    assert section is not None
    section.insert(
        0,
        ET.Element(
            "CashTransaction",
            {
                "accountId": "U0000000",
                "currency": "USD",
                "assetCategory": "",
                "fxRateToBase": "1",
                "symbol": "",
                "description": "WIRE DEPOSIT",
                "conid": "",
                "underlyingConid": "",
                "underlyingSymbol": "",
                "dateTime": "2026-05-01;08:00:00",
                "amount": "1000",
                "type": "Deposits/Withdrawals",
                "tradeID": "",
                "code": "",
            },
        ),
    )

    dataset = flex.parse_flex_dividend_dataset(
        ET.tostring(root, encoding="unicode")
    )

    assert [row.transaction_type for row in dataset.cash_transactions] == [
        "Dividends",
        "Withholding Tax",
    ]


def test_multiple_statement_periods_use_conservative_intersection() -> None:
    """Linked-account history is complete only across every statement period."""
    root = ET.fromstring(DIVIDEND_FIX.read_text(encoding="utf-8"))
    statements = root.find(".//FlexStatements")
    statement = root.find(".//FlexStatement")
    assert statements is not None and statement is not None
    second = ET.fromstring(ET.tostring(statement, encoding="unicode"))
    second.set("accountId", "ORG-ACCOUNT-2")
    second.set("fromDate", "2026-02-01")
    second.set("toDate", "2026-06-30")
    for row in second.iter():
        if "accountId" in row.attrib:
            row.set("accountId", "ORG-ACCOUNT-2")
    statements.append(second)

    dataset = flex.parse_flex_dividend_dataset(
        ET.tostring(root, encoding="unicode")
    )

    assert dataset.statement_from_date.isoformat() == "2026-02-01"
    assert dataset.statement_to_date.isoformat() == "2026-06-30"


@pytest.mark.parametrize(
    "section_name",
    [
        "AccountInformation",
        "CashTransactions",
        "ChangeInDividendAccruals",
        "OpenDividendAccruals",
        "OpenPositions",
        "FinancialInstrumentInformation",
    ],
)
def test_required_dividend_dataset_section_errors_are_safe(
    section_name: str,
) -> None:
    """A missing dividend section reports only its schema name."""
    xml_text = DIVIDEND_FIX.read_text(encoding="utf-8")

    with pytest.raises(flex.FlexQuerySchemaError) as excinfo:
        flex.parse_flex_dividend_dataset(_without_section(xml_text, section_name))

    error = excinfo.value
    assert error.missing_sections == [section_name]
    assert error.missing_fields == []
    assert section_name in str(error)
    assert "U0000000" not in str(error)
    assert "<FlexQueryResponse" not in str(error)


@pytest.mark.parametrize(
    ("section_name", "element_name", "attribute_name"),
    [
        ("AccountInformation", "AccountInformation", "currency"),
        ("CashTransactions", "CashTransaction", "amount"),
        (
            "ChangeInDividendAccruals",
            "ChangeInDividendAccrual",
            "quantity",
        ),
        ("OpenDividendAccruals", "OpenDividendAccrual", "payDate"),
        ("OpenPositions", "OpenPosition", "levelOfDetail"),
        (
            "FinancialInstrumentInformation",
            "SecurityInfo",
            "listingExchange",
        ),
    ],
)
def test_required_dividend_dataset_field_errors_are_safe(
    section_name: str,
    element_name: str,
    attribute_name: str,
) -> None:
    """An omitted selected field reports only its section and attribute."""
    xml_text = DIVIDEND_FIX.read_text(encoding="utf-8")

    with pytest.raises(flex.FlexQuerySchemaError) as excinfo:
        flex.parse_flex_dividend_dataset(
            _without_attribute(xml_text, element_name, attribute_name)
        )

    error = excinfo.value
    field_name = f"{section_name}.{attribute_name}"
    assert error.missing_sections == []
    assert error.missing_fields == [field_name]
    assert section_name in str(error)
    assert attribute_name in str(error)
    assert "U0000000" not in str(error)
    assert "<FlexQueryResponse" not in str(error)


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


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("Account Number: MASTER-ABC-999", "MASTER-ABC-999"),
        ("Account No=MASTER-NO-888", "MASTER-NO-888"),
        ("acctId=ADVISOR-XYZ-777", "ADVISOR-XYZ-777"),
        ("accountId=INSTITUTIONAL-66", "INSTITUTIONAL-66"),
        ("retail account DU1234567", "DU1234567"),
    ],
)
def test_flex_error_sanitizer_redacts_account_identifier_forms(
    message: str,
    secret: str,
) -> None:
    """Service errors remove labelled and retail account identifiers."""
    assert secret not in flex._redact_flex_message(message, ())


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


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("accountId=ORG-ACCOUNT-99 connection failed"),
        requests.HTTPError(
            "503 for https://example.invalid/report?t=secret-token&q=secret-query"
        ),
    ],
)
def test_fetch_flex_report_normalizes_request_failures(failure: Exception) -> None:
    """Network and HTTP failures cross the client boundary as safe Flex errors."""
    class FailedResponse:
        text = ""

        def raise_for_status(self) -> None:
            raise failure

    def failed_get(*_args, **_kwargs):
        if isinstance(failure, requests.ConnectionError):
            raise failure
        return FailedResponse()

    with pytest.raises(flex.FlexServiceError) as excinfo:
        flex.fetch_flex_report(
            "secret-token",
            "secret-query",
            http_get=failed_get,
        )

    message = str(excinfo.value)
    assert "secret-token" not in message
    assert "secret-query" not in message
    assert "ORG-ACCOUNT-99" not in message
    assert "https://" not in message


def test_fetch_flex_report_normalizes_malformed_handshake_xml() -> None:
    """Malformed service XML is a safe retrieval error, not a parser traceback."""
    class MalformedResponse:
        text = "<FlexStatementResponse"

        def raise_for_status(self) -> None:
            return None

    with pytest.raises(flex.FlexServiceError, match="malformed XML"):
        flex.fetch_flex_report(
            "secret-token",
            "secret-query",
            http_get=lambda *_args, **_kwargs: MalformedResponse(),
        )
