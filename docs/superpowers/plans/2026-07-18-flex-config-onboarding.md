# Flex Config Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `ib-trade-history` persist Flex credentials in the ignored workspace config through a validated, conversational setup flow.

**Architecture:** Add a typed `FlexCfg` to `ib_common.config` and null defaults to the shipped template. A dedicated `configure_flex.py` updates only the local config's `flex` section with round-trip YAML parsing. The trade-history script resolves a complete config pair first, then a complete environment pair, and rejects partial sources.

**Tech Stack:** Python 3.11+, Pydantic v2, `ruamel.yaml`, `argparse`, `pytest`.

## Global Constraints

- Real token and Query ID exist only in ignored `.ib-suite/config.yaml`; `config.example.yaml` always has null placeholders.
- `init_config.py` must retain its existing never-read/write-token contract.
- Do not print, serialize, log, commit, or include credentials in fixture data.
- Configuration is local validation only; setup never makes a Flex network request.
- Config and environment credentials are atomic pairs; never mix one value from each source.
- All Python modules use `from __future__ import annotations`, type annotations, and English docstrings.
- Do not add dependencies or cross the order-placement boundary.

---

### Task 1: Add Typed Flex Configuration Defaults

**Files:**
- Modify: `skills/ib-suite/ib-common/ib_common/config.py`
- Modify: `skills/ib-suite/ib-common/config.example.yaml`
- Modify: `skills/ib-suite/ib-common/tests/test_config.py`

**Interfaces:**
- Produces `FlexCfg(token: str | None, query_id: str | None)`.
- Adds `Config.flex: FlexCfg`, defaulting both fields to `None`.

- [ ] **Step 1: Write failing config tests**

Add:

```python
def test_flex_config_defaults_to_empty_credentials():
    cfg = load_config(FIX / "config_minimal.yaml")
    assert cfg.flex.token is None
    assert cfg.flex.query_id is None
```

- [ ] **Step 2: Run RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_config.py::test_flex_config_defaults_to_empty_credentials -q
```

Expected: FAIL because `Config.flex` does not exist.

- [ ] **Step 3: Implement model and template**

Add to `config.py`:

```python
class FlexCfg(BaseModel):
    """Workspace-local IBKR Flex credentials for the trade-history skill."""

    token: str | None = None
    query_id: str | None = None


class Config(BaseModel):
    connection: ConnectionCfg = Field(default_factory=ConnectionCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    flex: FlexCfg = Field(default_factory=FlexCfg)
    thresholds: dict[str, float] = Field(default_factory=dict)
```

Add to `config.example.yaml` after `storage`:

```yaml
flex:
  token: null       # workspace-local secret; never commit a real value
  query_id: null    # IBKR Flex Query ID
```

- [ ] **Step 4: Run GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-common/tests/test_config.py -q
```

Expected: PASS.

### Task 2: Add Safe Local Flex Credential Configurator

**Files:**
- Create: `skills/ib-suite/ib-trade-history/scripts/configure_flex.py`
- Create: `skills/ib-suite/ib-trade-history/tests/test_configure_flex.py`

**Interfaces:**
- Produces `configure_flex(config_path: str | Path, token: str, query_id: str, force: bool = False) -> dict`.
- Success result is exactly `{"config": "<path>", "ready": True}` and contains no credential value.

- [ ] **Step 1: Write failing tests**

Create tests for first write, comment preservation, empty values, overwrite
protection, forced paired replacement, and secret-free result:

```python
def test_configure_flex_writes_and_reloads_pair(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("# keep\nconnection:\n  port: 4001\n", encoding="utf-8")
    result = configure_flex.configure_flex(path, "token-value", "query-value")
    cfg = load_config(path)
    assert result == {"config": str(path), "ready": True}
    assert cfg.flex.token == "token-value"
    assert cfg.flex.query_id == "query-value"
    assert "token-value" not in str(result)
    assert "# keep" in path.read_text(encoding="utf-8")


def test_configure_flex_rejects_partial_existing_pair_without_force(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("flex:\n  token: old\n  query_id: null\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="--force"):
        configure_flex.configure_flex(path, "new-token", "new-query")
```

- [ ] **Step 2: Run RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q
```

Expected: FAIL because `configure_flex.py` does not exist.

- [ ] **Step 3: Implement configuration script**

Use `YAML(typ="rt")`, reject blank `token.strip()` or `query_id.strip()`, load
the existing document, inspect either existing `flex.token` or `flex.query_id`,
and raise `FileExistsError` without `force`. On write:

```python
doc.setdefault("flex", {})
doc["flex"]["token"] = token
doc["flex"]["query_id"] = query_id
```

Reload with `load_config(config_path)` and require both exact values before
returning `{"config": str(config_path), "ready": True}`. Add an argparse CLI
with `--config`, `--token`, `--query-id`, and `--force`; errors use
`parser.error(str(exc))`, never include input credential values.

- [ ] **Step 4: Run GREEN**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_configure_flex.py -q
```

Expected: PASS.

### Task 3: Resolve Config Credentials in Trade History and Document Setup

**Files:**
- Modify: `skills/ib-suite/ib-trade-history/scripts/trade_history.py`
- Modify: `skills/ib-suite/ib-trade-history/tests/test_trade_history.py`
- Modify: `skills/ib-suite/ib-trade-history/SKILL.md`
- Modify: `skills/ib-suite/SKILL.md`

**Interfaces:**
- Produces `resolve_flex_credentials(cfg: Config, environ: Mapping[str, str]) -> tuple[str, str]`.
- `trade_history()` calls it before the injected fetcher.

- [ ] **Step 1: Write failing source-resolution tests**

```python
def test_config_credentials_override_complete_environment_pair(tmp_path):
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
    config = tmp_path / "config.yaml"
    config.write_text("flex:\n  token: only-token\n  query_id: null\n", encoding="utf-8")
    with pytest.raises(ValueError, match="config.flex"):
        trade_history.resolve_flex_credentials(load_config(config), {})
```

- [ ] **Step 2: Run RED**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-trade-history/tests/test_trade_history.py -q
```

Expected: FAIL because `resolve_flex_credentials` does not exist.

- [ ] **Step 3: Implement atomic resolution and SKILL workflow**

Implement:

```python
def resolve_flex_credentials(cfg, environ):
    """Return one complete Flex credential pair from config or environment."""
    config_pair = (cfg.flex.token, cfg.flex.query_id)
    if all(config_pair):
        return config_pair
    if any(config_pair):
        raise ValueError("config.flex.token and config.flex.query_id must both be configured")
    env_pair = (environ.get("FLEX_TOKEN"), environ.get("FLEX_QUERY_ID"))
    if all(env_pair):
        return env_pair
    if any(env_pair):
        raise ValueError("FLEX_TOKEN and FLEX_QUERY_ID must both be configured")
    raise ValueError(
        "Flex credentials are not configured; run ib-trade-history setup or set both environment variables"
    )
```

Replace the current direct environment lookup with this function. Update
`ib-trade-history/SKILL.md` to check local `flex` fields first, ask for token
and Query ID when absent, run:

```bash
{baseDir}/../.venv/bin/python {baseDir}/scripts/configure_flex.py \
  --config .ib-suite/config.yaml --token '<provided-token>' --query-id '<provided-query-id>'
```

Document that setup persists plaintext credentials in ignored local config,
validates only local persistence, and never echoes values. Update the index
to say Flex credentials can be configured by `ib-trade-history`.

- [ ] **Step 4: Run focused tests**

```bash
skills/ib-suite/.venv/bin/python -m pytest \
  skills/ib-suite/ib-common/tests/test_config.py \
  skills/ib-suite/ib-trade-history/tests -q
```

Expected: PASS with no credential value in test output.

### Task 4: Regression and Secret-Safety Verification

**Files:** Verify only.

- [ ] **Step 1: Scan distributed files for real-looking configured secrets**

```bash
rg -n '^\s*(token|query_id):\s*[^n][^u][^l][^l]' \
  skills/ib-suite/ib-common/config.example.yaml || true
```

Expected: no output.

- [ ] **Step 2: Run complete tests**

```bash
skills/ib-suite/.venv/bin/python -m pytest skills -q
git diff --check
```

Expected: all tests pass and `git diff --check` prints no output.

- [ ] **Step 3: Inspect final scope**

```bash
git status --short
```

Expected: only the planned shared config, trade-history script/tests, and
SKILL documentation changes. Do not commit unless the user explicitly asks.
