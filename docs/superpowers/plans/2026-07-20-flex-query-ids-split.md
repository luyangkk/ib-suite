# Flex query-ids split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the shared `flex.query_ids` map into two independent top-level maps — `flex.trade_history_query_ids` and `flex.dividend_query_ids` — sharing one Flex token, so each skill resolves only the saved queries built for its own report sections.

**Architecture:** `FlexCfg` gains two `dict[str, str]` maps and drops `query_ids`. The window-key validator is reused across both. `configure_flex.py` gains a required `--target {trade_history,dividend}` for window writes. Each read path (`dividend_income.py`, `trade_history.py`) points at its own map. `select_flex_window` / `select_numeric_window` in `flex.py` are unchanged (map is a parameter); only call sites change.

**Tech Stack:** Python 3.11+, pydantic v2, ruamel.yaml, pytest. All paths read-only, Flex-only — no Gateway, market data, or orders.

## Global Constraints

- Python >= 3.11; every module starts with `from __future__ import annotations`.
- Data structures are pydantic v2 `BaseModel`; `FlexCfg` keeps `model_config = ConfigDict(coerce_numbers_to_str=True)`.
- Window keys are positive-integer day counts or `mtd` / `ytd`; reject others with `invalid Flex window key`.
- Hard cutover: no `query_ids` alias, no historical fallback. A stale `flex.query_ids` key is ignored by pydantic (extra key), so skills report their normal empty-map setup state.
- Credentials never enter stdout, logs, or version control; token passed only via `--token-stdin`.
- Read-only invariant: no file imports an order API; no Gateway start; no market-data request.
- Run tests with `skills/ib-suite/.venv/bin/python -m pytest`.

---

### Task 1: Split FlexCfg schema into two window maps

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/config.py:32-54`
- Test: `skills/ib-suite/ib-common/tests/test_config.py`

**Interfaces:**
- Produces: `FlexCfg.token: str | None`, `FlexCfg.trade_history_query_ids: dict[str, str]`, `FlexCfg.dividend_query_ids: dict[str, str]`. Field `query_ids` no longer exists. Validator `_validate_window_keys` applied to both map fields.

- [ ] **Step 1: Rewrite the FlexCfg tests**

Replace the three existing `query_ids` tests (`test_flex_config_defaults_to_empty_credentials`, `test_flex_query_ids_parsed_as_string_keyed_map`, `test_flex_query_ids_reject_unknown_string_key`) and the parametrized `test_flex_query_ids_reject_nonpositive_day_key` in `test_config.py` with the versions below. Keep every other test in the file unchanged.

```python
def test_flex_config_defaults_to_empty_credentials():
    """Configs without Flex settings expose empty workspace-local credentials."""
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.flex.token is None
    assert cfg.flex.trade_history_query_ids == {}
    assert cfg.flex.dividend_query_ids == {}


def test_flex_query_ids_parsed_as_string_keyed_maps(tmp_path):
    """Window keys load as strings on both maps; integer keys coerce to digits."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n"
        "  trade_history_query_ids:\n    7: q7\n    mtd: qm\n"
        "  dividend_query_ids:\n    365: q365\n    ytd: qy\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.flex.trade_history_query_ids == {"7": "q7", "mtd": "qm"}
    assert cfg.flex.dividend_query_ids == {"365": "q365", "ytd": "qy"}


def test_stale_query_ids_key_is_ignored(tmp_path):
    """The removed shared key no longer populates either map (hard cutover)."""
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n  query_ids:\n    7: q7\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.flex.trade_history_query_ids == {}
    assert cfg.flex.dividend_query_ids == {}


def test_flex_query_ids_reject_unknown_string_key(tmp_path):
    """A non-period, non-numeric key is a configuration error on either map."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  dividend_query_ids:\n    foo: x\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid Flex window key"):
        load_config(path)


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_flex_query_ids_reject_nonpositive_day_key(tmp_path, bad):
    """Numeric day keys must be strictly positive on either map."""
    path = tmp_path / "config.yaml"
    path.write_text(
        f"flex:\n  trade_history_query_ids:\n    '{bad}': x\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid Flex window key"):
        load_config(path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -v`
Expected: FAIL — `AttributeError`/validation errors on `trade_history_query_ids` / `dividend_query_ids` (fields not defined yet).

- [ ] **Step 3: Rewrite FlexCfg in config.py**

Replace the `FlexCfg` class body (lines 32-54) with:

```python
class FlexCfg(BaseModel):
    """Workspace-local IBKR Flex credentials, split per consuming skill."""

    # YAML integer window keys (e.g. `7:`) load as ints; coerce them to the
    # digit strings the model and validator expect.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    token: str | None = None
    trade_history_query_ids: dict[str, str] = Field(default_factory=dict)
    dividend_query_ids: dict[str, str] = Field(default_factory=dict)

    @field_validator("trade_history_query_ids", "dividend_query_ids")
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ib-suite/ib-common/ib_common/config.py skills/ib-suite/ib-common/tests/test_config.py
git commit -m "feat(ib-common): split FlexCfg into per-skill query-id maps"
```

---

### Task 2: Route configure_flex writes with --target

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/configure_flex.py:39-124` (`configure_flex`), `:127-154` (`main`)
- Test: `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`

**Interfaces:**
- Consumes: `FlexCfg.trade_history_query_ids`, `FlexCfg.dividend_query_ids` from Task 1.
- Produces: `configure_flex(config_path, token=None, windows=None, force=False, target=None)` — when `windows` is non-empty, `target` must be `"trade_history"` or `"dividend"`; it selects the map key `f"{target}_query_ids"`. CLI adds `--target {trade_history,dividend}`.

- [ ] **Step 1: Update the configurator tests**

In `test_configure_flex.py`, update the write/merge/clash tests to pass `target` and assert on the correct map, and add a missing-target test. Apply these edits:

Replace `test_configure_flex_writes_and_orders_period_windows`:

```python
def test_configure_flex_writes_and_orders_period_windows(tmp_path):
    """Numeric windows sort first by value, then period windows lexically."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")

    configure_flex.configure_flex(
        path, token="t",
        windows={"30": "q30", "ytd": "qy", "7": "q7", "mtd": "qm"},
        target="trade_history",
    )

    cfg = load_config(path)
    assert cfg.flex.trade_history_query_ids == {
        "7": "q7", "30": "q30", "mtd": "qm", "ytd": "qy"
    }
    assert list(cfg.flex.trade_history_query_ids) == ["7", "30", "mtd", "ytd"]
```

Replace `test_configure_flex_overwriting_period_requires_force`:

```python
def test_configure_flex_overwriting_period_requires_force(tmp_path):
    """Replacing an existing period key needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n  dividend_query_ids:\n    ytd: qy\n", encoding="utf-8"
    )

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(
            path, windows={"ytd": "qy-new"}, target="dividend"
        )

    configure_flex.configure_flex(
        path, windows={"ytd": "qy-new"}, target="dividend", force=True
    )
    assert load_config(path).flex.dividend_query_ids == {"ytd": "qy-new"}
```

Replace `test_configure_flex_writes_token_and_windows`:

```python
def test_configure_flex_writes_token_and_windows(tmp_path):
    """First setup writes token plus a windows map and keeps comments."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("# keep\nconnection:\n  port: 4001\n", encoding="utf-8")

    result = configure_flex.configure_flex(
        path, token="t", windows={7: "q7"}, target="dividend"
    )

    cfg = load_config(path)
    assert result == {"config": str(path), "ready": True}
    assert cfg.flex.token == "t"
    assert cfg.flex.dividend_query_ids == {"7": "q7"}
    assert "# keep" in path.read_text(encoding="utf-8")
    assert "q7" not in str(result)  # result carries no secret query id
```

Replace `test_configure_flex_merges_new_window_without_force`:

```python
def test_configure_flex_merges_new_window_without_force(tmp_path):
    """Adding a brand-new window merges into the target map only."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n  trade_history_query_ids:\n    7: q7\n",
        encoding="utf-8",
    )

    configure_flex.configure_flex(path, windows={30: "q30"}, target="trade_history")

    cfg = load_config(path)
    assert cfg.flex.trade_history_query_ids == {"7": "q7", "30": "q30"}
    assert cfg.flex.dividend_query_ids == {}
```

Replace `test_configure_flex_overwriting_window_requires_force`:

```python
def test_configure_flex_overwriting_window_requires_force(tmp_path):
    """Replacing an existing day key needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: t\n  trade_history_query_ids:\n    7: q7\n",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(
            path, windows={7: "q7-new"}, target="trade_history"
        )

    configure_flex.configure_flex(
        path, windows={7: "q7-new"}, target="trade_history", force=True
    )
    assert load_config(path).flex.trade_history_query_ids == {"7": "q7-new"}
```

Replace `test_configure_flex_overwriting_token_requires_force`:

```python
def test_configure_flex_overwriting_token_requires_force(tmp_path):
    """Replacing an existing token needs an explicit --force."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text(
        "flex:\n  token: old\n  trade_history_query_ids:\n    7: q7\n",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, token="new")

    configure_flex.configure_flex(path, token="new", force=True)
    assert load_config(path).flex.token == "new"
```

Replace `test_configure_flex_keeps_original_when_staged_validation_fails` body's config write and call to use the target map:

```python
def test_configure_flex_keeps_original_when_staged_validation_fails(
    tmp_path, monkeypatch
):
    """A failed staged reload leaves the config untouched and never echoes secrets."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    original = (
        "# retain\nflex:\n  token: old-token-secret\n"
        "  trade_history_query_ids:\n    7: old-query-secret\n"
    )
    path.write_text(original, encoding="utf-8")

    def fail_validation(_):
        raise ValueError("new-token-secret new-query-secret malformed")

    monkeypatch.setattr(configure_flex, "load_config", fail_validation)

    with pytest.raises(ValueError) as excinfo:
        configure_flex.configure_flex(
            path, token="new-token-secret", windows={30: "new-query-secret"},
            target="trade_history", force=True,
        )

    assert "new-token-secret" not in str(excinfo.value)
    assert "new-query-secret" not in str(excinfo.value)
    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".config.yaml.*.tmp"))
```

Add a new missing-target test and update the two CLI subprocess tests to pass `--target`:

```python
def test_configure_flex_windows_require_target(tmp_path):
    """Writing windows without a target is a usage error."""
    configure_flex = load_module()
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: t\n", encoding="utf-8")

    with pytest.raises(ValueError, match="--target"):
        configure_flex.configure_flex(path, windows={7: "q7"})


def test_cli_writes_windows_and_never_echoes_values(tmp_path):
    """The CLI persists windows to the chosen target and prints only the result."""
    path = tmp_path / "config.yaml"
    path.write_text("# local\n", encoding="utf-8")
    token, qid = "cli-token-secret", "cli-query-secret"

    ok = subprocess.run(
        [sys.executable, str(SPEC), "--config", str(path),
         "--token", token, "--window", f"7={qid}", "--target", "dividend"],
        capture_output=True, text=True, check=False,
    )

    assert ok.returncode == 0
    assert json.loads(ok.stdout) == {"config": str(path), "ready": True}
    assert token not in ok.stdout + ok.stderr
    assert qid not in ok.stdout + ok.stderr
    assert load_config(path).flex.dividend_query_ids == {"7": qid}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -v`
Expected: FAIL — `configure_flex()` has no `target` parameter / `--target` unknown argument.

- [ ] **Step 3: Add target routing in configure_flex.py**

In `configure_flex()`, change the signature and the window-map read/write to use the target map. Replace lines 39-99 as follows (keep the atomic-write block 101-124, but update its reload check — see the sub-edit below):

```python
def configure_flex(
    config_path: str | Path,
    token: str | None = None,
    windows: Mapping[str, str] | None = None,
    force: bool = False,
    target: str | None = None,
) -> dict:
    """Persist a Flex token and/or per-skill window map, preserving comments."""
    windows = {str(day): qid for day, qid in dict(windows or {}).items()}
    if token is not None and not token.strip():
        raise ValueError("Flex token must not be blank")
    if token is None and not windows:
        raise ValueError("provide a token or at least one window")
    if windows and target not in ("trade_history", "dividend"):
        raise ValueError(
            "writing Flex windows requires --target trade_history|dividend"
        )
    map_key = f"{target}_query_ids" if windows else None

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run ib-suite first-run setup before configuring Flex"
        )

    yaml = YAML(typ="rt")
    try:
        contents = path.read_text(encoding="utf-8")
        doc = yaml.load(contents)
        if doc is None:
            doc = yaml.load(f"{contents}\n{{}}\n")
    except (OSError, YAMLError):
        raise ValueError(_CONFIG_ERROR) from None

    if not isinstance(doc, Mapping):
        raise ValueError(_CONFIG_ERROR)

    flex = doc.get("flex")
    if flex is not None and not isinstance(flex, Mapping):
        raise ValueError(_CONFIG_ERROR)
    if flex is None:
        doc["flex"] = {}
        flex = doc["flex"]

    existing_norm: dict[str, str] = {}
    if map_key is not None:
        existing = flex.get(map_key)
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

    if token is not None:
        flex["token"] = token
    if windows:
        merged = dict(existing_norm)
        merged.update(windows)
        ordered = sorted(merged, key=lambda k: (0, int(k)) if k.isdigit() else (1, k))
        flex[map_key] = {k: merged[k] for k in ordered}
```

Then update the staged reload check (currently lines 113-115) to read the target map:

```python
        for day, query_id in windows.items():
            if getattr(config.flex, map_key).get(day) != query_id:
                raise ValueError("staged Flex windows did not reload exactly")
```

- [ ] **Step 4: Add the --target CLI argument**

In `main()`, after the `--window` argument (line 143) add:

```python
    parser.add_argument(
        "--target", choices=["trade_history", "dividend"],
        help="which skill's window map to write when using --window",
    )
```

And pass it through the call (replace line 151):

```python
        result = configure_flex(args.config, token, windows, args.force, args.target)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/ib-suite/ib-trade-history/scripts/configure_flex.py skills/ib-suite/ib-trade-history/tests/test_configure_flex.py
git commit -m "feat(ib-trade-history): route configure_flex windows by --target"
```

---

### Task 3: Point dividend income at dividend_query_ids

**Files:**
- Modify: `skills/ib-suite/ib-dividend-income/scripts/dividend_income.py:66-67` (`_validation_missing`), `:141-176` (read + state names)
- Test: `skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py`

**Interfaces:**
- Consumes: `FlexCfg.dividend_query_ids` from Task 1.
- Produces: dividend setup/coverage states name `flex.dividend_query_ids` (and `flex.dividend_query_ids.<days>` for coverage).

- [ ] **Step 1: Update the dividend CLI tests**

In `test_dividend_income_cli.py`, update `_write_config` and the state-name assertions. Change the `_write_config` helper's flex dict key from `query_ids` to `dividend_query_ids`:

```python
    flex: dict[str, Any] = {
        "dividend_query_ids": (
            {"365": "QUERY-SECRET-365"} if query_ids is None else query_ids
        ),
    }
```

Update the empty-map state test (`test_setup_empty_query_map_returns_stable_guide`) expected missing:

```python
        "missing": ["flex.dividend_query_ids"],
```

Update the coverage test (`test_coverage_insufficient_window_returns_required_state`) expected missing:

```python
        "missing": ["flex.dividend_query_ids.365"],
```

Update the blank-id test (`test_setup_blank_numeric_query_id_does_not_fetch`) expected missing:

```python
        "missing": ["flex.dividend_query_ids"],
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py -v`
Expected: FAIL — script still reads `cfg.flex.query_ids` (empty), so states/missing names mismatch.

- [ ] **Step 3: Update dividend_income.py read path and state names**

In `_validation_missing` (lines 66-67), match the new loc:

```python
    if any(
        location[:2] == ("flex", "dividend_query_ids") for location in locations
    ):
        return ["flex.dividend_query_ids"]
```

Replace the three `query_ids` reads and their state names (lines 141-147):

```python
    if any(
        not query_id.strip() for query_id in cfg.flex.dividend_query_ids.values()
    ):
        _log(logging.INFO, "setup_required", run_id=resolved_run_id)
        return _state("setup_required", ["flex.dividend_query_ids"], resolved_run_id)

    if not cfg.flex.dividend_query_ids:
        _log(logging.INFO, "setup_required", run_id=resolved_run_id)
        return _state("setup_required", ["flex.dividend_query_ids"], resolved_run_id)
```

Update the window selection call (line 162):

```python
        window, query_id, _ = select_flex_window(
            cfg.flex.dividend_query_ids,
            required_start,
            resolved_today,
            allow_partial=False,
        )
```

Update the coverage state (line 176):

```python
            [f"flex.dividend_query_ids.{required_days}"],
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ib-suite/ib-dividend-income/scripts/dividend_income.py skills/ib-suite/ib-dividend-income/tests/test_dividend_income_cli.py
git commit -m "feat(ib-dividend-income): read dividend_query_ids map"
```

---

### Task 4: Point trade history at trade_history_query_ids

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py:194-201`
- Test: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`

**Interfaces:**
- Consumes: `FlexCfg.trade_history_query_ids` from Task 1.

- [ ] **Step 1: Update the trade-history tests**

In `test_trade_history.py`, replace every inline config `query_ids:` block with `trade_history_query_ids:` (same indentation and values). The affected tests write YAML like:

```
"data:\n  base_currency: USD\nflex:\n  token: config-token\n"
"  trade_history_query_ids:\n    7: q7\n"
```

Apply this rename to the YAML in these tests: `test_resolve_flex_token_reads_config`, `test_resolve_flex_token_missing_is_actionable`, `test_orchestration_uses_injected_flex_fetcher_and_default_period`, `test_orchestration_selects_window_query_id_and_clips`, `test_orchestration_flags_coverage_gap`, `test_orchestration_redacts_request_exception_secrets`, `test_orchestration_preserves_sanitized_ibkr_error`, `test_orchestration_redacts_parse_error_from_flex_fetcher`, `test_orchestration_redacts_value_error_from_flex_fetcher`, `test_orchestration_preserves_actionable_parser_value_error`, `test_orchestration_rejects_invalid_flex_xml_without_parser_details`, and `test_main_redacts_request_exception_secrets`.

Note: `test_skill_metadata_and_source_preserve_read_only_boundary` asserts `"query_ids" in skill`; since `trade_history_query_ids` contains the substring `query_ids`, that assertion still holds after the SKILL.md edit in Task 5. Leave it unchanged.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -v`
Expected: FAIL — script reads `cfg.flex.query_ids` which is now empty, so window selection / token resolution behave differently than the renamed configs expect.

- [ ] **Step 3: Update trade_history.py read path**

Replace the two `cfg.flex.query_ids` reads (lines 195 and 200):

```python
        query_id, coverage_note = select_period_window(
            cfg.flex.trade_history_query_ids, period, resolved_today
        )
    else:
        start_date, end_date = resolve_period(start, end, resolved_today)
        _, query_id, coverage_note = select_flex_window(
            cfg.flex.trade_history_query_ids, start_date, resolved_today
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-trade-history/tests/test_trade_history.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ib-suite/ib-trade-history/scripts/trade_history.py skills/ib-suite/ib-trade-history/tests/test_trade_history.py
git commit -m "feat(ib-trade-history): read trade_history_query_ids map"
```

---

### Task 5: Update config template and skill documentation

**Files:**
- Modify: `skills/ib-suite/ib-common/config.example.yaml:13-15`
- Modify: `skills/ib-suite/ib-dividend-income/SKILL.md:57-92`
- Modify: `skills/ib-suite/ib-trade-history/SKILL.md` (setup section, ~28-55)
- Modify: `skills/ib-suite/SKILL.md:50,205`
- Modify: `skills/ib-suite/ib-dividend-income/flex-query-setup.md` (§5 commands)
- Modify: `skills/ib-suite/ib-trade-history/flex-query-setup.md` (§5 commands)

**Interfaces:**
- Consumes: field names and `--target` from Tasks 1-2. No code, no tests — docs only.

- [ ] **Step 1: Update config.example.yaml**

Replace lines 13-15:

```yaml
flex:
  token: null       # workspace-local secret; never commit a real value
  # keys: day count or 'mtd'/'ytd' -> Flex Query ID; quote values to preserve leading zeros
  trade_history_query_ids: {}   # queries for /ib-trade-history (Trades section)
  dividend_query_ids: {}        # queries for /ib-dividend-income (6 dividend sections)
```

- [ ] **Step 2: Update ib-dividend-income/SKILL.md**

In "Handle setup states", change every `flex.query_ids` reference to `flex.dividend_query_ids`, and add `--target dividend` to the configurator command. The command block becomes:

```bash
{baseDir}/../.venv/bin/python {baseDir}/../ib-trade-history/scripts/configure_flex.py \
  --config .ib-suite/config.yaml \
  --token-stdin \
  --target dividend \
  --window '365=<query-id>'
```

State that the dividend target requires a query carrying the six dividend sections (the full 7-section query also works).

- [ ] **Step 3: Update ib-trade-history/SKILL.md**

Change the `flex.query_ids` reference (~line 30) to `flex.trade_history_query_ids`, and add `--target trade_history` to each configure_flex command (the `7=<query-id>` and `mtd/ytd` examples):

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml \
  --token-stdin \
  --target trade_history \
  --window '7=<query-id>'
```

- [ ] **Step 4: Update ib-suite/SKILL.md**

At line 50 and line 205, replace `flex.query_ids` with a phrase naming both maps, e.g. `flex.trade_history_query_ids` / `flex.dividend_query_ids`.

- [ ] **Step 5: Update both flex-query-setup.md guides**

In §5 of `ib-dividend-income/flex-query-setup.md`, add `--target dividend` to each configure_flex command. In `ib-trade-history/flex-query-setup.md`, add `--target trade_history`. Clarify that the two skills now register independent Query IDs: the dividend map needs a query with the six dividend sections; the trade-history map may use a `Trades`-only query. Update §6 troubleshooting key names (`flex.dividend_query_ids` / `flex.trade_history_query_ids`).

- [ ] **Step 6: Verify docs reference no stale key**

Run: `grep -rn "flex.query_ids\|query_ids: {}\|--window '365" skills/ib-suite --include=*.md --include=*.yaml`
Expected: no bare `flex.query_ids` remains; every configure_flex command in docs carries `--target`.

Note: if the shell rejects `--include`, use: `grep -rn "flex.query_ids" skills/ib-suite` and review `.md` / `.yaml` hits.

- [ ] **Step 7: Commit**

```bash
git add skills/ib-suite/ib-common/config.example.yaml skills/ib-suite/ib-dividend-income/SKILL.md skills/ib-suite/ib-trade-history/SKILL.md skills/ib-suite/SKILL.md skills/ib-suite/ib-dividend-income/flex-query-setup.md skills/ib-suite/ib-trade-history/flex-query-setup.md
git commit -m "docs(ib-suite): document split trade-history/dividend query-id maps"
```

---

### Task 6: Full suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire test suite**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: PASS with no failures. Record the passed count in the closing summary.

- [ ] **Step 2: Grep for any residual shared key in code**

Run: `grep -rn "flex.query_ids\|\.query_ids\b" skills/ib-suite/ib-common/ib_common skills/ib-suite/ib-trade-history/scripts skills/ib-suite/ib-dividend-income/scripts`
Expected: no `cfg.flex.query_ids` or `FlexCfg.query_ids` references remain (only `trade_history_query_ids` / `dividend_query_ids`).

- [ ] **Step 3: Confirm read-only boundary intact**

Run: `grep -rn "placeOrder\|reqMktData\|IB()" skills/ib-suite/ib-trade-history/scripts skills/ib-suite/ib-dividend-income/scripts`
Expected: no order or market-data API introduced by this change.
