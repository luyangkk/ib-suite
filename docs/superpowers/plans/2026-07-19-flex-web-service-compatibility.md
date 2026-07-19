# Flex Web Service Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make read-only IBKR Flex Version 3 retrieval conform to the current official protocol, accept assignment rows with an explicitly empty order type, and surface credential-safe IBKR error codes.

**Architecture:** Keep transport and XML interpretation in `flex_fetch.py`, including a dedicated sanitized `FlexServiceError`. Keep `trade_history.py` as the orchestration boundary: preserve only the sanitized service error while continuing to redact network, malformed-XML, and arbitrary value errors. Existing injectable HTTP and fetch functions remain the offline test seams.

**Tech Stack:** Python 3.12, requests, xml.etree.ElementTree, pydantic v2, pytest.

## Global Constraints

- Use `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService` for Version 3 requests.
- Send an explicit stable `User-Agent` on SendRequest and GetStatement.
- Accept both `<url>` and `<Url>` response elements.
- Preserve only the IBKR numeric code and server message from Flex service errors; never expose credentials, reference codes, URLs, query strings, or raw XML.
- Accept `orderType=""` only when the attribute exists; reject a missing `orderType` attribute.
- Add no automatic retries or backoff beyond the existing GetStatement generation polling.
- Do not alter credential storage, Flex window selection, or any trading boundary.

---

### Task 1: Accept explicitly empty assignment order types

**Files:**
- Modify: `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`
- Modify: `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`

**Interfaces:**
- Consumes: `parse_flex_trade_records(xml_text: str) -> list[FlexTrade]`.
- Produces: `_present(trade: ET.Element, name: str) -> str`, which rejects an absent XML attribute but preserves its present value, including `""`.

- [ ] **Step 1: Write failing tests for empty versus absent `orderType`**

Append these tests after `test_parse_flex_trade_records_keeps_required_trade_history_fields`:

```python
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
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py::test_parse_flex_trade_records_accepts_present_empty_order_type \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py::test_parse_flex_trade_records_rejects_absent_order_type -v
```

Expected: the empty-value test fails with `Flex Trade field 'orderType' is missing`; the absent-value test passes.

- [ ] **Step 3: Implement presence-only validation for `orderType`**

Add beside `_required`:

```python
def _present(trade: ET.Element, name: str) -> str:
    """Return an attribute that may be empty, rejecting an omitted query field."""
    value = trade.get(name)
    if value is None:
        raise ValueError(
            f"Flex Trade field {name!r} is missing; enable it in the Flex Query Trades section"
        )
    return value
```

Change the `FlexTrade` construction from:

```python
order_type=_required(trade, "orderType"),
```

to:

```python
order_type=_present(trade, "orderType"),
```

- [ ] **Step 4: Run parser tests and confirm GREEN**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-gateway/tests/test_flex_fetch.py -v
```

Expected: all tests in `test_flex_fetch.py` pass.

- [ ] **Step 5: Commit the parser fix**

```bash
git add skills/ib-suite/ib-gateway/tests/test_flex_fetch.py skills/ib-suite/ib-gateway/scripts/flex_fetch.py
git commit -m "fix(ib-suite): accept empty assignment order type"
```

---

### Task 2: Use the current Flex Version 3 protocol

**Files:**
- Modify: `skills/ib-suite/ib-gateway/tests/test_flex_fetch.py`
- Modify: `skills/ib-suite/ib-gateway/scripts/flex_fetch.py`

**Interfaces:**
- Consumes: injected `http_get(url: str, params: dict, **kwargs)`.
- Produces: `FlexServiceError(code: str, message: str)`, `_raise_flex_error(root: ET.Element) -> None`, and the existing `fetch_flex_report(...) -> str` using the current endpoint and explicit headers.

- [ ] **Step 1: Replace the handshake test with parameterized URL-tag and header coverage**

Replace `test_fetch_flex_report_two_step_handshake` with:

```python
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
    assert all(call[2]["headers"]["User-Agent"] == "Python/3 ib-suite/0.1" for call in calls)
```

- [ ] **Step 2: Add a failing sanitized service-error test**

Append:

```python
def test_fetch_flex_report_raises_sanitized_ibkr_error():
    class FakeResp:
        text = (
            "<FlexStatementResponse><Status>Fail</Status>"
            "<ErrorCode>1014</ErrorCode><ErrorMessage>Query is invalid.</ErrorMessage>"
            "<RawSecret>token-and-query-must-not-leak</RawSecret>"
            "</FlexStatementResponse>"
        status_code = 200

        def raise_for_status(self):
            pass

    with pytest.raises(flex.FlexServiceError) as excinfo:
        flex.fetch_flex_report("secret-token", "secret-query", http_get=lambda *_args, **_kwargs: FakeResp())

    assert str(excinfo.value) == "IBKR Flex error 1014: Query is invalid."
    assert "secret-token" not in str(excinfo.value)
    assert "secret-query" not in str(excinfo.value)
    assert "token-and-query-must-not-leak" not in str(excinfo.value)
```

- [ ] **Step 3: Run the two protocol tests and confirm RED**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py::test_fetch_flex_report_uses_current_endpoint_headers_and_response_url \
  skills/ib-suite/ib-gateway/tests/test_flex_fetch.py::test_fetch_flex_report_raises_sanitized_ibkr_error -v
```

Expected: endpoint/header assertions fail and `FlexServiceError` is undefined.

- [ ] **Step 4: Implement current endpoint, headers, URL compatibility, and sanitized errors**

Replace the Flex constants and add the error type/helpers:

```python
_FLEX_BASE = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
)
_FLEX_HEADERS = {"User-Agent": "Python/3 ib-suite/0.1"}


class FlexServiceError(RuntimeError):
    """A credential-safe error returned by IBKR Flex Version 3."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"IBKR Flex error {code}: {message}")


def _raise_flex_error(root: ET.Element) -> None:
    """Raise a sanitized service error when a Version 3 response failed."""
    code = root.findtext("ErrorCode")
    if code:
        message = root.findtext("ErrorMessage") or "Unknown Flex service error."
        raise FlexServiceError(code, message)
```

Replace `fetch_flex_report` with the following implementation. It preserves only
the existing GetStatement readiness polling and does not retry SendRequest or
any other service error:

```python
def fetch_flex_report(token: str, query_id: str, http_get=requests.get,
                      poll_interval: float = 1.0, max_polls: int = 10) -> str:
    """Run the Flex two-step handshake and return raw statement XML."""
    send = http_get(
        f"{_FLEX_BASE}/SendRequest",
        params={"t": token, "q": query_id, "v": "3"},
        headers=_FLEX_HEADERS,
    )
    send.raise_for_status()
    root = ET.fromstring(send.text)
    _raise_flex_error(root)
    ref = root.findtext("ReferenceCode")
    url = (
        root.findtext("url")
        or root.findtext("Url")
        or f"{_FLEX_BASE}/GetStatement"
    )
    if not ref:
        raise RuntimeError("Flex SendRequest succeeded without a reference code")

    for _ in range(max_polls):
        stmt = http_get(
            url,
            params={"t": token, "q": ref, "v": "3"},
            headers=_FLEX_HEADERS,
        )
        stmt.raise_for_status()
        statement_root = ET.fromstring(stmt.text)
        if "Statement generation in progress" in stmt.text:
            time.sleep(poll_interval)
            continue
        _raise_flex_error(statement_root)
        return stmt.text
    return stmt.text
```

- [ ] **Step 5: Run Flex fetch tests and confirm GREEN**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-gateway/tests/test_flex_fetch.py -v
```

Expected: all Flex fetch tests pass.

- [ ] **Step 6: Commit the protocol fix**

```bash
git add skills/ib-suite/ib-gateway/tests/test_flex_fetch.py skills/ib-suite/ib-gateway/scripts/flex_fetch.py
git commit -m "fix(ib-suite): update Flex Version 3 transport"
```

---

### Task 3: Preserve safe IBKR errors through trade history

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`

**Interfaces:**
- Consumes: `FlexServiceError` from `flex_fetch.py`.
- Produces: `trade_history(...)` that re-raises sanitized IBKR service text while retaining generic redaction for unrelated fetch failures.

- [ ] **Step 1: Add the failing orchestration test**

Add after the existing request-exception redaction test:

```python
def test_orchestration_preserves_sanitized_ibkr_error(tmp_path):
    """Known Flex service codes stay actionable without leaking credentials."""
    token, query_id = "service-token", "service-query"
    config = tmp_path / "config.yaml"
    config.write_text(
        f"data:\n  base_currency: USD\nflex:\n  token: {token}\n"
        f"  query_ids:\n    7: {query_id}\n",
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
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py::test_orchestration_preserves_sanitized_ibkr_error -v
```

Expected: FAIL because the current broad exception handler replaces the service error with `Flex report retrieval failed`.

- [ ] **Step 3: Preserve only the dedicated safe error**

Change the import to:

```python
from flex_fetch import FlexServiceError, fetch_flex_report, parse_flex_trade_records
```

Split the fetch exception handling into:

```python
try:
    xml_text = fetcher(token, query_id)
except FlexServiceError as exc:
    raise RuntimeError(str(exc)) from None
except (requests.RequestException, RuntimeError, ET.ParseError, ValueError):
    raise RuntimeError(
        "Flex report retrieval failed; verify the Flex token, Flex Query "
        "settings, and service status"
    ) from None
```

- [ ] **Step 4: Run the complete trade-history tests and confirm GREEN**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests -v
```

Expected: all trade-history tests pass, including existing generic-redaction tests.

- [ ] **Step 5: Commit the orchestration fix**

```bash
git add skills/ib-suite/ib-trade-history/tests/test_trade_history.py skills/ib-suite/ib-trade-history/scripts/trade_history.py
git commit -m "fix(ib-suite): preserve sanitized Flex errors"
```

---

### Task 4: Full verification and live read-only check

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: the updated Flex transport, parser, and trade-history error boundary.
- Produces: evidence that offline regression tests and the actual seven-day query succeed.

- [ ] **Step 1: Run all affected offline suites**

Run:

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-gateway/tests \
  skills/ib-suite/ib-trade-history/tests -v
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 2: Check formatting and diff integrity**

Run:

```bash
git diff --check HEAD~3..HEAD
git status --short
```

Expected: no whitespace errors; only intentionally uncommitted files, if any, appear.

- [ ] **Step 3: Run the real seven-calendar-day read-only query**

Run:

```bash
skills/ib-suite/.venv/bin/python \
  skills/ib-suite/ib-trade-history/scripts/trade_history.py \
  --config .ib-suite/config.yaml
```

Expected: one JSON object with `start_date`, `end_date`, `trades`, and `summary`; no Flex error and no credential output.

- [ ] **Step 4: Report verification evidence**

Summarize the exact test count, live query date range, trade count, aggregate commission, and aggregate FIFO realized P/L. Do not print the Flex token, Query IDs, account number, request URLs, or reference codes.
