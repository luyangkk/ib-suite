# Flex Period Windows (MTD / YTD) — Design

Date: 2026-07-19
Skill: `ib-trade-history` (+ shared `ib-common`)
Branch: `feature/flex-multi-window`

## Problem

`ib-trade-history` picks a Flex Query from `flex.query_ids`, a `days -> Query ID`
map, choosing the smallest fixed-day window that still reaches the requested
start date. Two common intents — "month to date" and "year to date" — have no
first-class support. Approximating year-to-date with a fixed 365-day window
over-fetches and works against the goal of staying under IBKR's 1014 rate limit.

IBKR Flex natively supports **Month to Date** and **Year to Date** period
queries: their span tracks the calendar automatically (a few days at the start of
a month/year, the full span later), so they always cover "to date" exactly
without over-fetching.

## Goal

Let users register `mtd` / `ytd` Flex Query IDs alongside numeric-day windows,
and let `/ib-trade-history` select them explicitly via `--period mtd|ytd`.

Out of scope (unchanged hard boundaries): placing/modifying orders, live market
data, any write path into IB. Read-only throughout; no order API import.

## Decisions (from brainstorming)

1. **Role** — `mtd`/`ytd` are registered as entries in `query_ids`, selected by
   user intent. Feasible and preferred for YTD (native dynamic period beats a
   hardcoded 365-day window).
2. **Trigger** — an explicit `--period mtd|ytd` flag, decoupled from the
   date/day-count path.
3. **Data model** — a single `query_ids` map with **string keys**: numeric-day
   windows stored as digit strings (`'7'`, `'30'`), period windows as `'mtd'` /
   `'ytd'`.
4. **Argument relationship** — `--period` is mutually exclusive with
   `--start-date` / `--end-date`.
5. **Missing registration** — if `--period ytd` is requested but `'ytd'` is not
   registered, fall back to the numeric window pool: convert the period's start
   to a day gap, run the existing gap selection, and surface its `coverage_note`.

## Data Model (`ib-common/ib_common/config.py`)

`FlexCfg.query_ids` changes from `dict[int, str]` to `dict[str, str]`.

- Numeric-day windows are digit strings (`'7'`, `'30'`); period windows are
  `'mtd'` / `'ytd'`.
- A field validator enforces each key is **either** a positive-integer string
  (`k.isdigit()` and `int(k) > 0`) **or** one of `{'mtd', 'ytd'}` (lowercase),
  else `ValueError`. This blocks silent typos.
- YAML ints coerce to string keys on load, so an existing `{7: '1575839'}`
  becomes `{'7': '1575839'}` transparently.

Example:

```yaml
flex:
  token: null
  query_ids: {'7': '1575544', '30': '1580001', mtd: '1590002', ytd: '1590003'}
```

`config.example.yaml` updates the `query_ids` comment to show the mtd/ytd form.

## CLI Write Path (`ib-trade-history/scripts/configure_flex.py`)

`parse_window` returns `tuple[str, str]` (keys stay strings):

- Left side is `strip().lower()`. If it is `'mtd'` / `'ytd'`, use it directly.
- Otherwise validate as a positive integer **but keep the string form** (`'7'`),
  not `int`.
- Anything else raises the single format error, updated to:
  `window must use the format <days|mtd|ytd>=<id>, e.g. 7=1575544 or ytd=1590003`.

`configure_flex()`:

- Normalize existing keys with `str(...)` before merging, so int/str keys can't
  collide.
- Stable write-back ordering via a custom sort key: numeric-string keys first in
  numeric order, then `mtd`/`ytd` in lexical order. All keys are strings, so no
  `TypeError` on mixed sorting.
- Overwriting an existing `mtd`/`ytd` requires `--force`, same as numeric
  windows.

CLI example:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml --token '<token>' \
  --window 'mtd=<query-id>' --window 'ytd=<query-id>'
```

## Selection & Period Resolution (`ib-trade-history/scripts/trade_history.py`)

**(a) `select_flex_window` — numeric auto-select only.** Filter to numeric keys
first:

```python
numeric = {int(k): v for k, v in query_ids.items() if k.isdigit()}
```

Then the existing gap logic is unchanged (`gap = (today - start_date).days + 1`;
smallest window `>= gap`; else largest + `coverage_note`). `mtd`/`ytd` keys are
naturally excluded from auto-select. If `numeric` is empty (only period windows
registered), raise the existing "no Flex windows configured" error.

**(b) `resolve_period_bounds(period, today)` — pure function.**

- `'mtd'` -> `(today.replace(day=1), today)`
- `'ytd'` -> `(date(today.year, 1, 1), today)`

**(c) `select_period_window(query_ids, period, today)`.** If the period key is
registered, return its query id with `note=None`. Otherwise fall back to the
numeric pool: hand the period start from (b) to `select_flex_window` and pass
through the returned `coverage_note`. So an unregistered `--period ytd` uses the
largest numeric window as an approximation with a coverage note, rather than a
hard failure.

**Main flow (`trade_history()`)** — gains `period: str | None = None`.

- `period` given: `start_date, end_date = resolve_period_bounds(period, today)`;
  `_, query_id, coverage_note = select_period_window(cfg.flex.query_ids, period, today)`.
- Otherwise: the existing `resolve_period` + `select_flex_window` path, unchanged.

Both paths converge on `fetcher(token, query_id)` -> parse ->
`build_report(records, start_date, end_date, ...)`. `build_report`'s inclusive
in-range clip applies the period bounds naturally. The mutual-exclusion check
runs before period/date resolution.

## CLI Arguments (`trade_history.py` argparse)

```python
parser.add_argument("--period", choices=["mtd", "ytd"],
                    help="month-to-date or year-to-date; mutually exclusive with --start/--end-date")
```

`choices` rejects invalid values. Mutual exclusion is a hand-written check
(clearer than `add_mutually_exclusive_group`, since start/end are themselves a
pair): if `--period` is present together with either `--start-date` /
`--end-date`, raise `--period cannot be combined with --start-date/--end-date`.

## Output

`TradeHistoryReport` already carries `start_date` / `end_date` /
`coverage_note`. The period path fills the actual month-start/year-start..today
bounds. JSON shape is unchanged; consumers need no change.

## SKILL.md

- Prerequisites: add a period-window registration example (`--window 'ytd=<id>'`).
- Command: add a `--period` usage block; change the existing "this month = first
  of the month through today" guidance to prefer mapping to `--period mtd`, and
  "year to date" to `--period ytd`.

## Testing (TDD, red -> green; offline; injected fixed `today`)

**config — `ib-common/tests/test_config.py`**
- Mixed-key load `{7: 'a', mtd: 'b', ytd: 'c'}` -> `{'7':'a','mtd':'b','ytd':'c'}`.
- Validator rejects an unknown string key `{foo: 'x'}`.
- Validator rejects non-positive integer string keys `{'0': 'x'}`, `{'-3': 'x'}`.

**CLI — `ib-trade-history/tests/test_configure_flex.py`**
- `parse_window('mtd=q1')` -> `('mtd','q1')`; `'YTD=q2'` -> `('ytd','q2')`.
- `parse_window('7=q7')` -> `('7','q7')` (string, not int).
- `parse_window('foo=q')` raises the format error.
- Writing mtd/ytd reloads identically; mixed numeric+period write-back is stably
  ordered (numeric first, period after).
- Overwriting an existing `ytd` requires `--force`.

**core — `ib-trade-history/tests/test_trade_history.py`**
- `resolve_period_bounds('mtd', date(2026,7,19))` -> `(date(2026,7,1), date(2026,7,19))`;
  `'ytd'` -> `(date(2026,1,1), ...)`.
- `select_period_window` hits a registered key: returns its query id, note=None.
- `select_period_window` unregistered -> numeric fallback: selects a numeric
  window via the converted gap and carries a `coverage_note`.
- `select_flex_window` numeric-only: given a dict containing mtd/ytd, selection
  chooses among numeric keys, ignoring mtd/ytd.
- `select_flex_window` with only period keys (no numeric) -> raises
  "no Flex windows configured".
- Orchestration: `trade_history(..., period='mtd')` fetches with period bounds
  and clips; fake fetcher receives the right query id.
- Mutual exclusion: `period='ytd'` with start/end given -> raises.
- Redaction regression: on the period path, when the fetcher raises, neither
  token nor query id appears in the error message/traceback.

Run `skills/ib-suite/.venv/bin/python -m pytest skills -q` (baseline 195; ~12+
new cases).

## Safety

- Read-only unchanged: no order API import; connection stays read-only.
- No token/query-id value in stdout, error messages, or tracebacks — period path
  reuses the existing redaction pattern.
- No new dependencies. `configure_flex` write stays atomic (temp file + validate
  + `os.replace`).
