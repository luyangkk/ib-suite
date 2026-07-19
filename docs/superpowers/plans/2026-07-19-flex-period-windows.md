# Flex Period Windows (MTD / YTD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users register `mtd`/`ytd` Flex Query IDs alongside numeric-day windows and select them explicitly via `/ib-trade-history --period mtd|ytd`.

**Architecture:** Migrate `flex.query_ids` from `dict[int, str]` to a single `dict[str, str]` map (numeric-day windows as digit strings, period windows as `'mtd'`/`'ytd'`). Numeric auto-selection filters to digit keys only; a new `--period` flag drives period windows through dedicated pure functions, with fallback to the numeric pool when a period window is not registered. `--period` is mutually exclusive with `--start-date`/`--end-date`.

**Tech Stack:** Python 3.11+, pydantic v2, ruamel.yaml, pytest.

## Global Constraints

- Python **>= 3.11**; every module starts with `from __future__ import annotations`.
- All config types are pydantic v2 `BaseModel`; validators use `mode="after"` (default).
- **No new dependencies.** Do not add to `pyproject.toml` / `requirements.txt`.
- **Read-only invariant:** no order API import (`placeOrder`, `cancelOrder`, `reqGlobalCancel`, `bracketOrder`); connection stays read-only.
- **Redaction:** no `token` or query-id value in stdout, error messages, or tracebacks.
- `configure_flex` write stays atomic: temp file -> staged `load_config` validate -> `os.replace`.
- Run tests with `skills/ib-suite/.venv/bin/python -m pytest skills -q` (baseline: **195 passed**).
- Commit on branch `feature/flex-multi-window`; author 陆阳 <luyang.kk@bytedance.com>.
- Skill commands use `{baseDir}/../.venv/bin/python`; never absolute paths.

---

### Task 1: Migrate `query_ids` to string keys (atomic data-model migration)

Switch the key type everywhere at once so the suite never goes red. This adds the
validator that also permits `'mtd'`/`'ytd'`, makes `select_flex_window` filter to
numeric keys, makes `configure_flex` normalize/order string keys, makes
`parse_window` return string keys, and updates every existing test that asserted
integer keys.

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/config.py:30-34`
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py:43-65`
- Modify: `skills/ib-suite/ib-trade-history/scripts/configure_flex.py:20-31,72-92`
- Test: `skills/ib-suite/ib-common/tests/test_config.py:44-52`
- Test: `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py:27-30,41-78,141-157`
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py:436-467`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `FlexCfg.query_ids: dict[str, str]` with a field validator: each key is a
    positive-integer string (`k.isdigit()` and `int(k) > 0`) or one of
    `{'mtd', 'ytd'}`.
  - `select_flex_window(query_ids: dict[str, str], start_date: date, today: date) -> tuple[int, str, str | None]`
    (filters to numeric keys; returns numeric-day value, query id, coverage note).
  - `parse_window(spec: str) -> tuple[str, str]` (digit key kept as string).
  - `configure_flex(config_path, token=None, windows: Mapping[str, str] | None = None, force=False)`
    normalizes keys to strings and writes them numeric-first then lexical.

- [ ] **Step 1: Update the config test to expect string keys and add validator tests**

In `skills/ib-suite/ib-common/tests/test_config.py`, replace the body of
`test_flex_query_ids_parsed_as_int_keyed_map` (lines 44-52) and add validator
tests immediately after it:

```python
def test_flex_query_ids_parsed_as_string_keyed_map(tmp_path):
    """Window keys load as strings; YAML integer keys coerce to digit strings."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n  query_ids:\n    7: q7\n    30: q30\n"
        "    mtd: qm\n    ytd: qy\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.flex.query_ids == {"7": "q7", "30": "q30", "mtd": "qm", "ytd": "qy"}


def test_flex_query_ids_reject_unknown_string_key(tmp_path):
    """A non-period, non-numeric key is a configuration error, not a silent typo."""
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  query_ids:\n    foo: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Flex window key"):
        load_config(path)


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_flex_query_ids_reject_nonpositive_day_key(tmp_path, bad):
    """Numeric day keys must be strictly positive."""
    path = tmp_path / "config.yaml"
    path.write_text(f"flex:\n  query_ids:\n    '{bad}': x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Flex window key"):
        load_config(path)
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -q`
Expected: FAIL — old model has `dict[int, str]` (mixed-key load returns int keys) and no validator.

- [ ] **Step 3: Change the config model to string keys with a validator**

In `skills/ib-suite/ib-common/ib_common/config.py`, update the import (line 10)
and the `FlexCfg` class (lines 30-34):

```python
from pydantic import BaseModel, Field, field_validator
```

```python
class FlexCfg(BaseModel):
    """Workspace-local IBKR Flex credentials for the trade-history skill."""

    token: str | None = None
    query_ids: dict[str, str] = Field(default_factory=dict)

    @field_validator("query_ids")
    @classmethod
    def _validate_window_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Keys are positive-integer day counts or the periods 'mtd'/'ytd'."""
        for key in value:
            if key in ("mtd", "ytd"):
                continue
            if not key.isdigit() or int(key) <= 0:
                raise ValueError(
                    f"invalid Flex window key {key!r}; use a positive day count "
                    "or 'mtd'/'ytd'"
                )
        return value
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Update `select_flex_window` unit tests to string-keyed inputs**

In `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`, change the
input dicts (the expected integer `days` values stay) in the four
`select_flex_window` tests (lines 436-467):

```python
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
```

Also add a test (after line 467) proving non-numeric keys are ignored by
auto-selection:

```python
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
```

- [ ] **Step 6: Run the select tests to verify failure**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q -k select_flex_window`
Expected: FAIL — old `select_flex_window` compares string keys against an int gap (`TypeError`) and has no period filtering.

- [ ] **Step 7: Rewrite `select_flex_window` to filter numeric keys**

In `skills/ib-suite/ib-trade-history/scripts/trade_history.py`, replace the
function (lines 43-65):

```python
def select_flex_window(
    query_ids: dict[str, str], start_date: date, today: date
) -> tuple[int, str, str | None]:
    """Pick the smallest configured numeric-day window that reaches start_date.

    Only digit keys participate; 'mtd'/'ytd' are handled by the period path.
    gap counts today inclusively. When the request predates every window, use
    the largest and return a coverage note instead of dropping data or failing.
    """
    numeric = {int(k): v for k, v in query_ids.items() if k.isdigit()}
    if not numeric:
        raise ValueError(
            "no Flex windows configured; run configure_flex.py with --window"
        )
    gap = (today - start_date).days + 1
    covering = sorted(days for days in numeric if days >= gap)
    if covering:
        chosen = covering[0]
        return chosen, numeric[chosen], None
    largest = max(numeric)
    note = (
        f"requested start date precedes the largest configured Flex window "
        f"({largest} days); results may be incomplete"
    )
    return largest, numeric[largest], note
```

- [ ] **Step 8: Run the select tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q -k select_flex_window`
Expected: PASS.

- [ ] **Step 9: Update `configure_flex` tests to string keys**

In `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`:

Line 30 — `parse_window` returns a string key:

```python
    assert configure_flex.parse_window("7=q7") == ("7", "q7")
```

Line 52 (`test_configure_flex_writes_token_and_windows`):

```python
    assert cfg.flex.query_ids == {"7": "q7"}
```

Line 65 (`test_configure_flex_merges_new_window_without_force`):

```python
    assert load_config(path).flex.query_ids == {"7": "q7", "30": "q30"}
```

Line 78 (`test_configure_flex_overwriting_window_requires_force`):

```python
    configure_flex.configure_flex(path, windows={7: "q7-new"}, force=True)
    assert load_config(path).flex.query_ids == {"7": "q7-new"}
```

Line 157 (`test_cli_writes_windows_and_never_echoes_values`):

```python
    assert load_config(path).flex.query_ids == {"7": qid}
```

- [ ] **Step 10: Run the configure_flex tests to verify failure**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q`
Expected: FAIL — `parse_window` still returns `(7, "q7")` and reloaded config still has int keys.

- [ ] **Step 11: Update `parse_window` and `configure_flex` for string keys**

In `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`, replace
`parse_window` (lines 20-31):

```python
def parse_window(spec: str) -> tuple[str, str]:
    """Parse a '<days>=<query-id>' window spec into (day-string, query_id)."""
    days_text, sep, query_id = spec.partition("=")
    key = days_text.strip()
    if not sep or not key or not query_id.strip():
        raise ValueError("window must use the format <days>=<id>, e.g. 7=1575544")
    if not key.isdigit() or int(key) <= 0:
        raise ValueError("window must use the format <days>=<id>, e.g. 7=1575544")
    return key, query_id.strip()
```

Normalize the incoming windows at the top of `configure_flex` (replace line 41):

```python
    windows = {str(day): qid for day, qid in dict(windows or {}).items()}
```

Replace the existing-map handling and clash detection (lines 72-85) so keys are
compared as strings:

```python
    existing = flex.get("query_ids")
    if existing is not None and not isinstance(existing, Mapping):
        raise ValueError(_CONFIG_ERROR)
    existing_norm = {str(day): qid for day, qid in dict(existing or {}).items()}

    if not force:
        if token is not None and flex.get("token") is not None:
            raise FileExistsError(
                "Flex token already exists; pass --force to replace it"
            )
        clashes = [day for day in windows if day in existing_norm]
        if clashes:
            raise FileExistsError(
                f"Flex windows already exist for {sorted(clashes)}; pass --force to replace"
            )
```

Replace the merge/write-back (lines 89-92) with a stable numeric-first ordering:

```python
    if windows:
        merged = dict(existing_norm)
        merged.update(windows)
        ordered = sorted(merged, key=lambda k: (0, int(k)) if k.isdigit() else (1, k))
        flex["query_ids"] = {k: merged[k] for k in ordered}
```

- [ ] **Step 12: Run the full suite to verify green**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: PASS (195 passed).

- [ ] **Step 13: Commit**

```bash
git add skills/ib-suite/ib-common/ib_common/config.py \
  skills/ib-suite/ib-common/tests/test_config.py \
  skills/ib-suite/ib-trade-history/scripts/trade_history.py \
  skills/ib-suite/ib-trade-history/scripts/configure_flex.py \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py
git commit -m "refactor(ib-suite): migrate flex query_ids to string keys"
```

---

### Task 2: Accept `mtd`/`ytd` period windows in the CLI

Broaden `parse_window` and its error message so users can register period
windows; `configure_flex`'s string handling from Task 1 already stores and
orders them.

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/configure_flex.py:20-31`
- Test: `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py:27-38`

**Interfaces:**
- Consumes: `configure_flex(...)` string-key handling from Task 1.
- Produces: `parse_window` additionally accepts `'mtd'`/`'ytd'` (case-insensitive),
  returning them lowercase.

- [ ] **Step 1: Write failing tests for period-window parsing and registration**

In `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`, add after
`test_parse_window_accepts_days_equals_id` (line 30):

```python
@pytest.mark.parametrize(
    ("spec", "expected"),
    [("mtd=q1", ("mtd", "q1")), ("YTD=q2", ("ytd", "q2")), ("Mtd=q3", ("mtd", "q3"))],
)
def test_parse_window_accepts_period_keys(spec, expected):
    """Period specs parse case-insensitively into lowercase period keys."""
    configure_flex = load_module()
    assert configure_flex.parse_window(spec) == expected


def test_configure_flex_writes_and_orders_period_windows(tmp_path):
    """Numeric windows sort first by value, then period windows lexically."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")

    configure_flex.configure_flex(
        path, token="t", windows={"30": "q30", "ytd": "qy", "7": "q7", "mtd": "qm"}
    )

    cfg = load_config(path)
    assert cfg.flex.query_ids == {"7": "q7", "30": "q30", "mtd": "qm", "ytd": "qy"}
    assert list(cfg.flex.query_ids) == ["7", "30", "mtd", "ytd"]


def test_configure_flex_overwriting_period_requires_force(tmp_path):
    """Replacing an existing period key needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    ytd: qy\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, windows={"ytd": "qy-new"})

    configure_flex.configure_flex(path, windows={"ytd": "qy-new"}, force=True)
    assert load_config(path).flex.query_ids == {"ytd": "qy-new"}
```

Update the malformed-spec regex (line 37) to match the broadened message that
Step 3 introduces:

```python
    with pytest.raises(ValueError, match=r"days\|mtd\|ytd"):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q`
Expected: FAIL — `parse_window` rejects `mtd`/`ytd`, and the malformed regex no longer matches the old message.

- [ ] **Step 3: Broaden `parse_window` to accept period keys**

In `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`, replace
`parse_window` (lines 20-31):

```python
_WINDOW_FORMAT = (
    "window must use the format <days|mtd|ytd>=<id>, e.g. 7=1575544 or ytd=1590003"
)


def parse_window(spec: str) -> tuple[str, str]:
    """Parse a '<days|mtd|ytd>=<query-id>' spec into (key, query_id)."""
    key_text, sep, query_id = spec.partition("=")
    key = key_text.strip().lower()
    if not sep or not key or not query_id.strip():
        raise ValueError(_WINDOW_FORMAT)
    if key in ("mtd", "ytd"):
        return key, query_id.strip()
    if not key.isdigit() or int(key) <= 0:
        raise ValueError(_WINDOW_FORMAT)
    return key, query_id.strip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ib-suite/ib-trade-history/scripts/configure_flex.py \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py
git commit -m "feat(ib-suite): register mtd/ytd flex windows via configure_flex"
```

---

### Task 3: Add period-bound and period-window resolution

Two pure functions in `trade_history.py`: one converts a period to inclusive
date bounds, the other selects the period's query id (falling back to the
numeric pool when the period is unregistered).

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py` (add functions after `select_flex_window`, around line 66)
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py` (add after the select tests)

**Interfaces:**
- Consumes: `select_flex_window(query_ids, start_date, today)` from Task 1.
- Produces:
  - `resolve_period_bounds(period: str, today: date) -> tuple[date, date]`
  - `select_period_window(query_ids: dict[str, str], period: str, today: date) -> tuple[str, str | None]`
    returns `(query_id, coverage_note)`.

- [ ] **Step 1: Write failing tests for both functions**

In `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`, add:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q -k period`
Expected: FAIL with "module 'trade_history' has no attribute 'resolve_period_bounds'".

- [ ] **Step 3: Implement both functions**

In `skills/ib-suite/ib-trade-history/scripts/trade_history.py`, add after
`select_flex_window` (after line 65):

```python
def resolve_period_bounds(period: str, today: date) -> tuple[date, date]:
    """Return inclusive (start, end) bounds for a month- or year-to-date period."""
    if period == "mtd":
        return today.replace(day=1), today
    if period == "ytd":
        return date(today.year, 1, 1), today
    raise ValueError(f"unknown period {period!r}; use 'mtd' or 'ytd'")


def select_period_window(
    query_ids: dict[str, str], period: str, today: date
) -> tuple[str, str | None]:
    """Return (query_id, note) for a period, falling back to the numeric pool.

    A registered period key wins with no note. Otherwise the period's start date
    drives numeric auto-selection, carrying its coverage note through.
    """
    if period in query_ids:
        return query_ids[period], None
    start_date, _ = resolve_period_bounds(period, today)
    _, query_id, note = select_flex_window(query_ids, start_date, today)
    return query_id, note
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q -k period`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ib-suite/ib-trade-history/scripts/trade_history.py \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "feat(ib-suite): resolve mtd/ytd period bounds and window selection"
```

---

### Task 4: Wire `--period` into orchestration and the CLI

Add the `period` parameter to `trade_history()`, branch the main flow, enforce
mutual exclusion with `--start-date`/`--end-date`, and expose the `--period`
argument. Update the one existing test that hard-codes the defaults tuple.

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py:174-223`
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py:405-433` and additions

**Interfaces:**
- Consumes: `resolve_period_bounds`, `select_period_window` from Task 3;
  `select_flex_window` from Task 1.
- Produces: `trade_history(config_path, start, end, fetcher=..., today=None, period: str | None = None) -> dict`.

- [ ] **Step 1: Write failing tests for period orchestration and mutual exclusion**

In `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`, add:

```python
def test_orchestration_period_fetches_and_clips(tmp_path):
    """--period mtd fetches the period's query id and clips to month-to-date."""
    xml = (Path(__file__).parent / "fixtures" / "flex_trade_history_sample.xml").read_text()
    config = tmp_path / "config.yaml"
    config.write_text(
        "data:\n  base_currency: USD\nflex:\n  token: t\n"
        "  query_ids:\n    7: q7\n    mtd: qm\n",
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
        "data:\n  base_currency: USD\nflex:\n  token: t\n  query_ids:\n    mtd: qm\n",
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
        f"  query_ids:\n    ytd: {query_id}\n",
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
```

Update the defaults-tuple monkeypatch in
`test_main_redacts_request_exception_secrets` (line 421) for the new trailing
`period` parameter:

```python
    monkeypatch.setattr(
        trade_history.trade_history, "__defaults__", (failed_fetch, None, None)
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q -k "period or redacts_request_exception"`
Expected: FAIL — `trade_history()` has no `period` parameter.

- [ ] **Step 3: Branch the main flow on `period`**

In `skills/ib-suite/ib-trade-history/scripts/trade_history.py`, replace the
`trade_history` signature and window-resolution block (lines 174-194):

```python
def trade_history(
    config_path: str,
    start: str | None,
    end: str | None,
    fetcher: Callable[[str, str], str] = fetch_flex_report,
    today: date | None = None,
    period: str | None = None,
) -> dict:
    """Fetch Flex trades once and return a JSON-safe inclusive-period report."""
    if period is not None and (start is not None or end is not None):
        raise ValueError(
            "--period cannot be combined with --start-date/--end-date"
        )
    cfg = load_config(config_path)
    base_currency = (cfg.data.base_currency or "").upper()
    if not base_currency:
        raise ValueError(
            "data.base_currency is required for Flex trade-history conversion; "
            "set it in .ib-suite/config.yaml"
        )
    token = resolve_flex_token(cfg)
    resolved_today = today or date.today()
    if period is not None:
        start_date, end_date = resolve_period_bounds(period, resolved_today)
        query_id, coverage_note = select_period_window(
            cfg.flex.query_ids, period, resolved_today
        )
    else:
        start_date, end_date = resolve_period(start, end, resolved_today)
        _, query_id, coverage_note = select_flex_window(
            cfg.flex.query_ids, start_date, resolved_today
        )
```

(The `try/except` fetch block and `build_report(...)` return below stay
unchanged.)

- [ ] **Step 4: Add the `--period` CLI argument**

In `main()` (after line 218, the `--end-date` argument), add:

```python
    parser.add_argument(
        "--period", choices=["mtd", "ytd"],
        help="month-to-date or year-to-date; mutually exclusive with --start-date/--end-date",
    )
```

Update the success call (line 221):

```python
        print(json.dumps(
            trade_history(args.config, args.start_date, args.end_date, period=args.period)
        ))
```

- [ ] **Step 5: Run the full suite to verify green**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: PASS (all prior tests plus the new period tests).

- [ ] **Step 6: Commit**

```bash
git add skills/ib-suite/ib-trade-history/scripts/trade_history.py \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "feat(ib-suite): add --period mtd/ytd to trade-history"
```

---

### Task 5: Update SKILL.md and config example

Document the period windows and the `--period` command, and refresh the config
example comment. Keep the existing `--window '7=<query-id>'` registration block
that `test_skill_guides_window_registration_and_force_replacement` asserts.

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/SKILL.md:26-72`
- Modify: `skills/ib-suite/ib-common/config.example.yaml:13-15`
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py:228-260`

**Interfaces:**
- Consumes: CLI behavior from Tasks 2 and 4.
- Produces: SKILL.md `--period` documentation; example config shows mtd/ytd.

- [ ] **Step 1: Write a failing test asserting the SKILL documents `--period`**

In `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`, add inside
`test_skill_metadata_and_source_preserve_read_only_boundary` (after line 235,
`assert "--window" in skill`):

```python
    assert "--period" in skill
    assert "ytd" in skill
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q -k read_only_boundary`
Expected: FAIL — SKILL.md has no `--period` / `ytd` text yet.

- [ ] **Step 3: Update SKILL.md**

In `skills/ib-suite/ib-trade-history/SKILL.md`, extend the registration guidance
(around lines 30-37) to mention period windows — add after the existing
`--window '7=<query-id>'` example block:

```markdown
Register month-to-date and year-to-date windows the same way, using `mtd`/`ytd`
in place of a day count:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml --token '<provided-token>' \
  --window 'mtd=<query-id>' --window 'ytd=<query-id>'
```
```

Add a `--period` command block after the seven-day default example (after line
68), and update the interpretation guidance (lines 70-72):

```markdown
For month-to-date or year-to-date, use `--period` (mutually exclusive with the
date arguments):

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/trade_history.py \
  --config .ib-suite/config.yaml --period mtd
```

Interpret "this month" / "month to date" as `--period mtd`, and "this year" /
"year to date" as `--period ytd`. If the matching `mtd`/`ytd` window is not
registered, the runtime falls back to the numeric windows and adds a
`coverage_note`. Interpret "last month" as the previous calendar month via
`--start-date`/`--end-date`; ask one clarifying question for ambiguous phrases
such as "recently".
```

(Replace the existing lines 70-72 paragraph with the paragraph above so the
guidance is not duplicated.)

- [ ] **Step 4: Update the config example comment**

In `skills/ib-suite/ib-common/config.example.yaml`, replace line 15:

```yaml
  query_ids: {}     # keys: day count or 'mtd'/'ytd' -> Flex Query ID, e.g. {"7": "1575544", ytd: "1590003"}
```

- [ ] **Step 5: Run the full suite to verify green**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/ib-suite/ib-trade-history/SKILL.md \
  skills/ib-suite/ib-common/config.example.yaml \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "docs(ib-suite): document --period mtd/ytd trade-history windows"
```

---

## Self-Review

**1. Spec coverage:**
- Data model `dict[str,str]` + validator → Task 1 (Steps 1-4).
- CLI writes numeric + mtd/ytd, stable ordering, force → Task 1 (Steps 9-11) + Task 2.
- `select_flex_window` numeric-only, period-only raises → Task 1 (Steps 5-8).
- `resolve_period_bounds` / `select_period_window` (registered + fallback) → Task 3.
- `--period` flag, mutual exclusion, main flow branch, output unchanged → Task 4.
- SKILL.md + config example → Task 5.
- Redaction regression on period path → Task 4 (Step 1, `test_orchestration_period_redacts_fetch_failure`).
- Existing int-key tests migrated → Task 1 (Steps 5, 9) + Task 4 (`__defaults__`).
All spec sections map to a task. No gaps.

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". Every code step shows full code and every command has expected output.

**3. Type consistency:**
- `select_flex_window(query_ids: dict[str,str], start_date, today) -> tuple[int, str, str|None]` — same signature in Task 1 definition and Task 3/4 call sites.
- `select_period_window(...) -> tuple[str, str|None]` — defined Task 3, unpacked as `query_id, coverage_note` in Task 4. Consistent.
- `resolve_period_bounds(period, today) -> tuple[date, date]` — same in Task 3 and Task 4.
- `parse_window(spec) -> tuple[str, str]` — Task 1 defines, Task 2 broadens the same signature.
- `trade_history(..., period=None)` — trailing param matches the `__defaults__` 3-tuple update in Task 4.

No inconsistencies found.
