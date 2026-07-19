# First-run Config Detection & Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-run config detection so that when `.ib-suite/config.yaml` is missing, the top-level `ib-suite` index guides the user through generating one via a deterministic `init_config.py` script.

**Architecture:** The top-level `ib-suite/SKILL.md` becomes always-loaded (`always: true`, no `requires.config`) and owns onboarding + routing; a new deterministic `scripts/init_config.py` reads `config.example.yaml` (round-trip via ruamel.yaml), overrides only `connection.port` per a `--mode` flag (default live/4001), and refuses to overwrite an existing config unless `--force`. Sub-skill gating is unchanged — they stay gated until config exists, and the index picks up the slack.

**Tech Stack:** Python >= 3.11, ruamel.yaml (already a dependency), pydantic v2, pytest.

## Global Constraints

- Python >= 3.11; every module starts with `from __future__ import annotations`.
- Read-only invariant: no module imports or calls any order-placing IB API.
- No new runtime dependencies (ruamel.yaml, pydantic, pytest already present).
- `SKILL.md` commands use `{baseDir}` placeholder and `.venv/bin/python`; never hardcode absolute/user paths. The literal token `<workspace>` must NOT appear in any runnable command (only `{baseDir}` is resolved at runtime); prose may use `<workspace>/` for readability.
- Entry scripts use `argparse`, validate required args, exit non-zero with an actionable message on failure, and print structured results to stdout.
- Never print or write any token; `$FLEX_TOKEN` is prose-only.
- Never commit a real `config.yaml` or live snapshot; `.ib-suite/` and `docs/` are gitignored.
- Detection/generation target path is the relative `.ib-suite/config.yaml`.

---

### Task 1: `init_config.py` — deterministic config generator

**Files:**
- Create: `skills/ib-suite/scripts/init_config.py`
- Test: `skills/ib-suite/scripts/tests/test_init_config.py`

**Interfaces:**
- Consumes: `ib_common.config.load_config(path) -> Config` (existing) for the round-trip validation test.
- Produces: `init_config(template: str | Path, out: str | Path, mode: str = "live", force: bool = False) -> dict` returning `{"config": str(out_path), "mode": mode, "port": int}`. Raises `FileExistsError` when `out` exists and `force` is False. `mode` must be `"live"` (port 4001) or `"paper"` (port 4002); any other value raises `ValueError`.

- [ ] **Step 1: Write the failing tests**

Create `skills/ib-suite/scripts/tests/test_init_config.py`. The test module must make the sibling `init_config.py` importable the same way the repo's other script tests do (via `sys.path.insert`), and locate the real template relative to the repo tree.

```python
from __future__ import annotations
import sys
from pathlib import Path

import pytest

# make the sibling scripts/ dir importable (mirrors analyze.py's sys.path pattern)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import init_config  # noqa: E402

from ib_common.config import load_config  # noqa: E402

# the shipped template lives under ib-common/ next to the scripts dir's parent
TEMPLATE = SCRIPTS_DIR.parent / "ib-common" / "config.example.yaml"


def test_live_mode_sets_port_4001(tmp_path):
    out = tmp_path / "config.yaml"
    result = init_config.init_config(TEMPLATE, out, mode="live")
    assert result["port"] == 4001
    cfg = load_config(out)
    assert cfg.connection.port == 4001


def test_paper_mode_sets_port_4002(tmp_path):
    out = tmp_path / "config.yaml"
    result = init_config.init_config(TEMPLATE, out, mode="paper")
    assert result["port"] == 4002
    assert load_config(out).connection.port == 4002


def test_default_mode_is_live(tmp_path):
    out = tmp_path / "config.yaml"
    result = init_config.init_config(TEMPLATE, out)
    assert result["mode"] == "live"
    assert result["port"] == 4001


def test_template_defaults_preserved(tmp_path):
    out = tmp_path / "config.yaml"
    init_config.init_config(TEMPLATE, out, mode="paper")
    cfg = load_config(out)
    # storage.root and base_currency come straight from the template
    assert cfg.storage.root == ".ib-suite/data"
    assert cfg.data.base_currency is None
    # thresholds copied verbatim (spot-check a couple of keys)
    assert cfg.thresholds["leverage_crit"] == 2.0
    assert cfg.thresholds["single_position_weight_warn"] == 0.20


def test_refuse_overwrite_without_force(tmp_path):
    out = tmp_path / "config.yaml"
    out.write_text("original: keep-me\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_config.init_config(TEMPLATE, out, mode="live")
    # original content untouched
    assert out.read_text(encoding="utf-8") == "original: keep-me\n"


def test_force_overwrites(tmp_path):
    out = tmp_path / "config.yaml"
    out.write_text("original: replace-me\n", encoding="utf-8")
    init_config.init_config(TEMPLATE, out, mode="live", force=True)
    assert load_config(out).connection.port == 4001


def test_invalid_mode_raises(tmp_path):
    out = tmp_path / "config.yaml"
    with pytest.raises(ValueError):
        init_config.init_config(TEMPLATE, out, mode="demo")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/scripts/tests/test_init_config.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'init_config'`.

- [ ] **Step 3: Write minimal implementation**

Create `skills/ib-suite/scripts/init_config.py`:

```python
# skills/ib-suite/scripts/init_config.py
"""First-run config generator: template -> config.yaml with the one decision
that matters (paper vs live -> connection.port). Deterministic and offline.

Never overwrites an existing config unless --force. Never reads or writes any
token. The IB read-only boundary is unaffected: this only writes config.yaml.
"""
from __future__ import annotations
import argparse
from pathlib import Path

from ruamel.yaml import YAML

_PORT_BY_MODE = {"live": 4001, "paper": 4002}


def init_config(template: str | Path, out: str | Path, mode: str = "live",
                force: bool = False) -> dict:
    """Generate config.yaml from the template, overriding only the port.

    Reads the template round-trip (comments preserved), sets
    connection.port from `mode`, leaves storage.root / base_currency /
    thresholds at their template values, and writes to `out`.
    """
    if mode not in _PORT_BY_MODE:
        raise ValueError(f"mode must be one of {sorted(_PORT_BY_MODE)}, got {mode!r}")
    out_path = Path(out)
    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists; pass --force to rebuild it")

    yaml = YAML(typ="rt")
    with open(template, "r", encoding="utf-8") as f:
        doc = yaml.load(f)

    port = _PORT_BY_MODE[mode]
    doc.setdefault("connection", {})
    doc["connection"]["port"] = port

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(doc, f)

    return {"config": str(out_path), "mode": mode, "port": port}


if __name__ == "__main__":
    default_template = Path(__file__).resolve().parent.parent / "ib-common" / "config.example.yaml"
    parser = argparse.ArgumentParser(description="Generate config.yaml for first-run setup (read-only project).")
    parser.add_argument("--template", default=str(default_template),
                        help="path to config.example.yaml")
    parser.add_argument("--out", default=".ib-suite/config.yaml",
                        help="target config path (workspace-local)")
    parser.add_argument("--mode", choices=sorted(_PORT_BY_MODE), default="live",
                        help="live => port 4001, paper => port 4002")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing config")
    args = parser.parse_args()
    print(init_config(args.template, args.out, args.mode, args.force))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/scripts/tests/test_init_config.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/ib-suite/scripts/init_config.py skills/ib-suite/scripts/tests/test_init_config.py
git commit -m "feat(ib-suite): add deterministic init_config.py for first-run setup"
```

---

### Task 2: Wire onboarding into the top-level `ib-suite/SKILL.md`

**Files:**
- Modify: `skills/ib-suite/SKILL.md` (frontmatter + new "0. First-run setup" section)

**Interfaces:**
- Consumes: `scripts/init_config.py` CLI from Task 1 (`--mode`, `--out`, `--force`).
- Produces: no code interface; a documented onboarding flow OpenClaw/agents follow.

- [ ] **Step 1: Relax the index gating**

In `skills/ib-suite/SKILL.md`, edit the frontmatter `metadata.openclaw` block so the index is always loadable and no longer gated on config. Current block:

```yaml
metadata:
  openclaw:
    homepage: https://docs.openclaw.ai/tools/skills
    requires:
      bins: [python3]
      config: [config.yaml]
    os: [darwin, linux]
```

Replace with (drop `config:`, add `always: true`):

```yaml
metadata:
  openclaw:
    homepage: https://docs.openclaw.ai/tools/skills
    always: true
    requires:
      bins: [python3]
    os: [darwin, linux]
```

- [ ] **Step 2: Add the "0. First-run setup" section**

Insert a new section immediately before `## 1. Directory overview` in `skills/ib-suite/SKILL.md`:

```markdown
## 0. First-run setup

Before running any sub-skill, make sure a config exists. This index owns
onboarding; the sub-skills stay gated until `config.yaml` is present.

1. **Detect.** If `.ib-suite/config.yaml` already exists, config is ready —
   skip to §2. Otherwise continue.
   ```bash
   test -f .ib-suite/config.yaml && echo "config ready" || echo "needs setup"
   ```
2. **Ensure the venv** (only if missing):
   ```bash
   test -d {baseDir}/.venv || bash {baseDir}/scripts/setup_venv.sh
   ```
3. **Ask the user one question:** connect to **live** (real account, port 4001)
   or **paper** (simulated, port 4002)? Default is **live** — every connection
   in this toolchain is `readonly=True`, so live is read-only too.
4. **Generate the config** with the chosen mode (defaults to live):
   ```bash
   {baseDir}/.venv/bin/python {baseDir}/scripts/init_config.py \
     --mode live --out .ib-suite/config.yaml
   ```
   It refuses to overwrite an existing config unless you add `--force`.
5. **Report back:** the config path and the resulting mode/port. Remind the
   user to start IB Gateway with **Read-Only API** enabled before `/ib-sync`,
   and to `export FLEX_TOKEN=…` only when pulling Flex dividends/history.
6. Proceed to §2 and run `/ib-sync` → `/ib-analyze`.

Runtime config and data stay workspace-local under `<workspace>/.ib-suite/`
(gitignored); the skill dir ships only code and `config.example.yaml`.
```

- [ ] **Step 3: Verify frontmatter is valid YAML and paths resolve**

Run:
```bash
skills/ib-suite/.venv/bin/python -c "import io,sys; from ruamel.yaml import YAML; t=open('skills/ib-suite/SKILL.md').read(); fm=t.split('---')[1]; d=YAML(typ='safe').load(io.StringIO(fm)); assert d['metadata']['openclaw']['always'] is True; assert 'config' not in d['metadata']['openclaw'].get('requires',{}); print('frontmatter OK')"
```
Expected: `frontmatter OK`.

Also confirm no literal `<workspace>` appears inside a fenced command:
```bash
grep -n '<workspace>' skills/ib-suite/SKILL.md
```
Expected: matches only in prose lines (the "Runtime config…" sentence), never inside a ```bash block.

- [ ] **Step 4: Commit**

```bash
git add skills/ib-suite/SKILL.md
git commit -m "feat(ib-suite): index owns first-run onboarding (always-load, no config gate)"
```

---

### Task 3: Full-suite regression + end-to-end onboarding check

**Files:**
- None modified (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1–2.

- [ ] **Step 1: Run the full test suite**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: PASS — baseline 54 plus the 7 new `init_config` tests = 61 passed.

- [ ] **Step 2: End-to-end onboarding dry run (paper, temp path)**

Generate into a throwaway path so no real config is touched, then load it back:
```bash
skills/ib-suite/.venv/bin/python skills/ib-suite/scripts/init_config.py \
  --mode paper --out /tmp/ib-suite-e2e/config.yaml
skills/ib-suite/.venv/bin/python -c "from ib_common.config import load_config; c=load_config('/tmp/ib-suite-e2e/config.yaml'); print('port', c.connection.port, '| root', c.storage.root)"
```
Expected: script prints `{'config': '/tmp/ib-suite-e2e/config.yaml', 'mode': 'paper', 'port': 4002}`; loader prints `port 4002 | root .ib-suite/data`.

- [ ] **Step 3: Verify refuse-overwrite from the CLI**

```bash
skills/ib-suite/.venv/bin/python skills/ib-suite/scripts/init_config.py \
  --mode live --out /tmp/ib-suite-e2e/config.yaml; echo "exit=$?"
```
Expected: prints a `FileExistsError` traceback (or the actionable message) and `exit=1` (non-zero). Then confirm `--force` succeeds:
```bash
skills/ib-suite/.venv/bin/python skills/ib-suite/scripts/init_config.py \
  --mode live --out /tmp/ib-suite-e2e/config.yaml --force; echo "exit=$?"
```
Expected: prints the live/4001 result dict and `exit=0`.

- [ ] **Step 4: Clean up the throwaway artifact**

```bash
rm -rf /tmp/ib-suite-e2e
```

- [ ] **Step 5: Commit (if any incidental fixes were needed)**

No source changes are expected in this task. If regression fixes were required, commit them:
```bash
git add -A
git commit -m "test(ib-suite): verify first-run onboarding end-to-end"
```
If nothing changed, skip the commit.

---

## Notes for the implementer

- The venv must exist first: `bash skills/ib-suite/scripts/setup_venv.sh` if `skills/ib-suite/.venv` is absent.
- `ruamel.yaml` ships via `ib-common` deps; `YAML(typ="rt")` preserves the template's inline comments (e.g. `# 4002 = paper, 4001 = live`).
- Do not add order-placing code or flip any read-only flag.
- `docs/` is gitignored in this repo, matching existing plans/specs — the plan/spec files live on disk but are not committed.
