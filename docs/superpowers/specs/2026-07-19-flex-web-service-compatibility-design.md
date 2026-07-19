# Flex Web Service compatibility design

## Goal

Restore reliable read-only IBKR Flex report retrieval against the current
Version 3 protocol while preserving actionable, credential-safe failures.
The change must not add order placement or any other write path to IBKR.

## Confirmed failure modes

The existing client uses the legacy
`gdcdyn.interactivebrokers.com/Universal/servlet` base URL and does not set an
explicit `User-Agent`. With valid local credentials and a valid seven-day Query
ID, that request returned IBKR error 1001. The same credentials and parameters
successfully generated a report through the current documented
`ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService` endpoint with
an explicit `User-Agent`.

Current Version 3 success responses may spell the statement URL element as
lowercase `<url>`, while the client reads only `<Url>`. The returned report also
contains assignment-generated `Trade` rows where the `orderType` attribute is
present but empty. The parser currently treats an empty value as though the
field were omitted from the Flex Query.

Finally, the trade-history entrypoint catches every Flex service failure and
replaces it with one generic message. That prevents callers from distinguishing
errors such as 1001, 1014, and 1018 even though IBKR supplies a safe numeric code
and explanation.

## Design

### Request protocol

`flex_fetch.py` will use the current documented Version 3 base URL. Every
SendRequest and GetStatement request will carry an explicit, stable
`User-Agent` identifying Python and ib-suite. Existing dependency injection via
`http_get` remains intact so tests stay offline.

The SendRequest parser will accept both `<url>` and `<Url>`, preferring the URL
provided by IBKR and falling back to the current GetStatement endpoint only when
neither spelling is present.

### Flex service errors

The fetch layer will parse Version 3 error responses and raise a dedicated
runtime error whose public text contains only the IBKR numeric error code and
the server-provided error message. It must never contain the token, Query ID,
reference code, request URL, query string, or raw response body.

`trade_history.py` will preserve this sanitized error text instead of replacing
it with the existing generic retrieval error. Network exceptions and malformed
XML will continue to produce a credential-safe generic message. No generalized
retry will be added; each request will fail according to the returned IBKR
status so configuration and protocol errors remain visible.

### Empty order type

The trade parser will distinguish an absent `orderType` attribute from a
present-but-empty attribute:

- absent: reject with the existing Flex Query configuration hint;
- present but empty: accept and preserve it as an empty string.

This supports IBKR-generated assignment rows without weakening detection of a
Flex Query that omitted the field entirely. Other currently required fields
retain their existing non-empty validation.

## Tests

Offline tests will cover:

1. the current base URL and explicit `User-Agent` on both request stages;
2. lowercase `<url>` and legacy uppercase `<Url>` response elements;
3. a present-but-empty `orderType` accepted as an empty string;
4. an absent `orderType` still rejected;
5. IBKR error codes/messages preserved through the trade-history boundary;
6. tokens, Query IDs, reference codes, request URLs, and raw XML absent from
   formatted failures;
7. the existing Flex-fetch and trade-history test suites remain green.

## Non-goals

- No automatic retries or backoff.
- No changes to credential storage or Flex window selection.
- No relaxation of other required trade fields.
- No IB Gateway dependency and no trading operations.
