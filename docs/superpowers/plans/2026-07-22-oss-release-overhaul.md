# OSS Release Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standard GitHub open-source scaffolding (license, community files, CI, templates, metadata) to the ib-suite repo before publishing, without changing any business code or skill behavior.

**Architecture:** Pure documentation/config additions at the repo root and under `.github/`, plus metadata-only edits to `pyproject.toml`, `CLAUDE.md`, and the two READMEs. No source, schema, or test logic changes. Each task ends in one reviewable commit.

**Tech Stack:** Markdown, YAML (GitHub Actions + issue forms), TOML (`pyproject.toml`), MIT license text, Contributor Covenant v2.1, Keep a Changelog.

## Global Constraints

- No business-code changes: scripts, `ib_common`, `ib_analyst`, schema, thresholds untouched.
- No lint/format toolchain (no `ruff`/`pre-commit`) — out of scope this pass.
- No directory restructuring, no skill renames, no behavior changes.
- License: MIT, year `2026`, holder `luyangkk`.
- Repo slug for URLs: `https://github.com/luyangkk/ib-suite`.
- CI: `ubuntu-latest`, Python matrix `3.11` and `3.12`; steps = checkout → setup-python → `bash skills/ib-suite/scripts/setup_venv.sh` → `skills/ib-suite/.venv/bin/python -m pytest skills -q`.
- SECURITY contact: GitHub private security advisory (no personal email).
- Never commit `.ib-suite/`, real `config.yaml`, `.venv/`, or live snapshots.
- Commit style: `type(scope): summary` explaining the why.

---

### Task 1: MIT LICENSE

**Files:**
- Create: `LICENSE`

**Interfaces:**
- Consumes: nothing.
- Produces: `LICENSE` file at repo root that the README license badge and `pyproject.toml` `license` field reference.

- [ ] **Step 1: Create `LICENSE` with the exact MIT text**

```text
MIT License

Copyright (c) 2026 luyangkk

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Verify GitHub recognizes it**

Run: `head -1 LICENSE`
Expected: `MIT License`

- [ ] **Step 3: Commit**

```bash
git add LICENSE
git commit -m "docs: add MIT LICENSE"
```

---

### Task 2: CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `CONTRIBUTING.md` referenced by README Contributing sections and the PR template.

- [ ] **Step 1: Create `CONTRIBUTING.md`**

Distill the dev flow from `CLAUDE.md` §5–§8, §10. Content:

```markdown
# Contributing to ib-suite

Thanks for your interest in improving ib-suite. This is a **read-only**
Interactive Brokers diagnostics suite — please read the boundaries below before
opening a PR.

## Read-only invariant (non-negotiable)

- Every IB connection uses `readonly=True`. No module may import an order API.
- No order placement / modification / cancellation, no live WhatIf margin checks,
  no real-time market-data streaming, no write path into IB — ever.
- Never commit or print a token, Query ID, account number, or user path.

## Development setup

Requires Python >= 3.11 on macOS or Linux.

```bash
# Bootstrap the shared virtualenv (idempotent; installs ib-common editable + deps)
bash skills/ib-suite/scripts/setup_venv.sh
```

Runtime config and data live under a workspace-local `.ib-suite/` directory that
is gitignored. Never commit a real `config.yaml` or a live snapshot.

## Workflow

1. Read only the files relevant to your change; search rather than guess.
2. Follow TDD: write a failing test → run it red → implement → run it green.
3. Make the smallest change that works; reuse existing schema, the `Finding`
   vocabulary, `grade()`, `render()`, and storage helpers. No unrelated
   refactors or reformatting.
4. Keep `SKILL.md`, scripts, `ib_common` schema/thresholds, and tests consistent.

## Testing

```bash
# Full test run
skills/ib-suite/.venv/bin/python -m pytest skills -q

# A single skill, e.g. dividend income
skills/ib-suite/.venv/bin/python -m pytest skills/ib-suite/ib-dividend-income -q
```

All tests must pass before you open a PR.

## Commit messages

Use `type(scope): summary`, e.g. `fix(ib-dividend-income): reconcile gross with Flex data`.
Explain the *why*, not just the *what*. Prefer new commits over amending.

## Pull requests

- Confirm the read-only boundary is respected and no secrets/runtime data are
  included (`.ib-suite/`, real `config.yaml`, live snapshots, `.venv/`).
- Fill in the PR template checklist.
- See [SECURITY.md](SECURITY.md) for reporting vulnerabilities and
  [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations.

For the full architecture and conventions, read [CLAUDE.md](CLAUDE.md).
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: add contributing guide"
```

---

### Task 3: CODE_OF_CONDUCT.md

**Files:**
- Create: `CODE_OF_CONDUCT.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `CODE_OF_CONDUCT.md` referenced by CONTRIBUTING and issue templates.

- [ ] **Step 1: Create `CODE_OF_CONDUCT.md` with Contributor Covenant v2.1**

Use the verbatim Contributor Covenant v2.1 text. For the enforcement contact
line, use the placeholder:

```markdown
Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the community leaders responsible for enforcement via a
**GitHub private security advisory** on this repository, or by opening a
confidential report through the repository's Security tab.
```

Include all standard sections: Our Pledge, Our Standards, Enforcement
Responsibilities, Scope, Enforcement, Enforcement Guidelines (Correction /
Warning / Temporary Ban / Permanent Ban), and the Attribution footer pointing to
`https://www.contributor-covenant.org/version/2/1/code_of_conduct.html`.

- [ ] **Step 2: Commit**

```bash
git add CODE_OF_CONDUCT.md
git commit -m "docs: add Contributor Covenant code of conduct"
```

---

### Task 4: SECURITY.md

**Files:**
- Create: `SECURITY.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `SECURITY.md` referenced by CONTRIBUTING, issue templates, and CoC.

- [ ] **Step 1: Create `SECURITY.md`**

```markdown
# Security Policy

## Read-only by design

ib-suite connects to Interactive Brokers with `readonly=True` and never places,
modifies, or cancels orders. It never writes to your IB account. If you find any
code path that could violate this boundary, treat it as a security issue and
report it privately.

## Credentials

- Flex tokens, Query IDs, account numbers, and user paths must never appear in
  stdout, logs, or committed files.
- Real config and runtime data live only under the gitignored `.ib-suite/`
  directory. Committed fixtures are desensitized.

## Supported versions

The project is pre-1.0; only the latest `main` receives security fixes.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| older commits | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead, use
GitHub's private vulnerability reporting: open a
[private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
via the repository's **Security** tab. We aim to acknowledge reports within a
few days.
```

- [ ] **Step 2: Commit**

```bash
git add SECURITY.md
git commit -m "docs: add security policy"
```

---

### Task 5: CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `CHANGELOG.md` at repo root.

- [ ] **Step 1: Create `CHANGELOG.md` in Keep a Changelog format**

```markdown
# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Standard open-source project scaffolding: `LICENSE` (MIT), `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.editorconfig`, GitHub Actions CI, and
  issue/PR templates.
- Bilingual `README.md` / `README.zh-CN.md`.
- Packaging metadata (`authors`, `license`, `urls`, classifiers) for `ib-common`.

## [0.1.0] - 2026-07-22

### Added
- Initial `ib-suite` read-only Interactive Brokers diagnostics suite: index skill
  plus `ib-gateway`, `ib-account-overview`, `ib-positions-overview`,
  `ib-daily-pnl`, `ib-trade-history`, `ib-dividend-income`, `ib-options-overview`,
  and `ib-portfolio-analyst`, backed by the shared `ib-common` library.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add changelog"
```

---

### Task 6: .editorconfig

**Files:**
- Create: `.editorconfig`

**Interfaces:**
- Consumes: nothing.
- Produces: `.editorconfig` at repo root.

- [ ] **Step 1: Create `.editorconfig`**

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.py]
indent_size = 4

[*.{yml,yaml,json,toml}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
```

- [ ] **Step 2: Commit**

```bash
git add .editorconfig
git commit -m "chore: add editorconfig"
```

---

### Task 7: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `skills/ib-suite/scripts/setup_venv.sh` (existing), which produces `skills/ib-suite/.venv`.
- Produces: a workflow named `CI` on branch `main`, referenced by README badges as `luyangkk/ib-suite/actions/workflows/ci.yml`.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Bootstrap shared virtualenv
        run: bash skills/ib-suite/scripts/setup_venv.sh

      - name: Run tests
        run: skills/ib-suite/.venv/bin/python -m pytest skills -q
```

- [ ] **Step 2: Validate the YAML parses**

Run: `skills/ib-suite/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Confirm setup_venv.sh honors the CI Python**

Read `skills/ib-suite/scripts/setup_venv.sh` to confirm it picks a Python >= 3.11 from PATH (the one `setup-python` installs). If it hardcodes a specific interpreter that would ignore the matrix version, note it in the PR description rather than changing script behavior in this pass.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest on push and pull requests"
```

---

### Task 8: Issue templates + config

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`

**Interfaces:**
- Consumes: `SECURITY.md` (linked from config.yml).
- Produces: three issue-form files under `.github/ISSUE_TEMPLATE/`.

- [ ] **Step 1: Create `bug_report.yml`**

```yaml
name: Bug report
description: Report a defect in an ib-suite skill or the shared library
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for the report. **Do not paste tokens, Query IDs, account
        numbers, or live account data.** Redact everything sensitive first.
  - type: input
    id: skill
    attributes:
      label: Which skill / command?
      placeholder: e.g. /ib-dividend-income
    validations:
      required: true
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: What did you expect, and what did you get instead?
    validations:
      required: true
  - type: textarea
    id: repro
    attributes:
      label: Steps to reproduce
      placeholder: |
        1. Configure ...
        2. Run ...
        3. See error ...
    validations:
      required: true
  - type: textarea
    id: environment
    attributes:
      label: Environment
      placeholder: OS, Python version, live vs paper
    validations:
      required: true
  - type: checkboxes
    id: safety
    attributes:
      label: Safety confirmation
      options:
        - label: I confirm this report contains no tokens, Query IDs, account numbers, or other credentials.
          required: true
```

- [ ] **Step 2: Create `feature_request.yml`**

```yaml
name: Feature request
description: Suggest an enhancement that stays within the read-only boundary
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: |
        ib-suite is strictly read-only. Requests that place, modify, or cancel
        orders, or that write to an IB account, are out of scope.
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What are you trying to accomplish?
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposed solution
    validations:
      required: true
  - type: checkboxes
    id: scope
    attributes:
      label: Scope confirmation
      options:
        - label: This request keeps the read-only boundary (no order placement/modification/cancellation, no write path to IB).
          required: true
```

- [ ] **Step 3: Create `config.yml`**

```yaml
blank_issues_enabled: false
contact_links:
  - name: Security vulnerability
    url: https://github.com/luyangkk/ib-suite/security/advisories/new
    about: Report security issues privately — do not open a public issue.
```

- [ ] **Step 4: Validate all three YAML files parse**

Run: `for f in .github/ISSUE_TEMPLATE/*.yml; do skills/ib-suite/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('$f')); print('ok', '$f')"; done`
Expected: `ok` for each file

- [ ] **Step 5: Commit**

```bash
git add .github/ISSUE_TEMPLATE/
git commit -m "chore: add issue templates"
```

---

### Task 9: Pull request template

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `.github/PULL_REQUEST_TEMPLATE.md`.

- [ ] **Step 1: Create `.github/PULL_REQUEST_TEMPLATE.md`**

```markdown
## Summary

<!-- What does this change and why? -->

## Checklist

- [ ] `skills/ib-suite/.venv/bin/python -m pytest skills -q` passes locally
- [ ] Change stays within the read-only boundary (no order placement/modification/cancellation, no write path to IB)
- [ ] No secrets or runtime data included (`.ib-suite/`, real `config.yaml`, live snapshots, `.venv/`)
- [ ] `SKILL.md`, scripts, `ib_common` schema/thresholds, and tests are consistent
- [ ] Commit messages follow `type(scope): summary`

## Notes

<!-- Anything reviewers should know: residual risk, follow-ups, screenshots. -->
```

- [ ] **Step 2: Commit**

```bash
git add .github/PULL_REQUEST_TEMPLATE.md
git commit -m "chore: add pull request template"
```

---

### Task 10: Complete pyproject.toml metadata

**Files:**
- Modify: `skills/ib-suite/ib-common/pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces: enriched `[project]` metadata. No dependency changes.

- [ ] **Step 1: Add metadata fields to the `[project]` table**

In `skills/ib-suite/ib-common/pyproject.toml`, extend the existing `[project]`
table (keep `name`, `version`, `description`, `requires-python`, and
`dependencies` exactly as they are) by adding:

```toml
license = { text = "MIT" }
authors = [{ name = "luyangkk" }]
keywords = ["interactive-brokers", "ibkr", "portfolio", "read-only", "openclaw", "agent-skill"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Financial and Insurance Industry",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Office/Business :: Financial :: Investment",
]

[project.urls]
Homepage = "https://github.com/luyangkk/ib-suite"
Repository = "https://github.com/luyangkk/ib-suite"
Issues = "https://github.com/luyangkk/ib-suite/issues"
```

Do not add a `readme` pointing at the root README — the package lives in a
subdirectory and the root README is not packaged with it; omit `readme` to avoid
a build-time missing-file error.

- [ ] **Step 2: Verify the venv still builds `ib-common` cleanly**

Run: `skills/ib-suite/.venv/bin/python -c "import tomllib; tomllib.load(open('skills/ib-suite/ib-common/pyproject.toml','rb')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

Run: `skills/ib-suite/.venv/bin/python -m pytest skills -q`
Expected: same pass count as the pre-change baseline.

- [ ] **Step 4: Commit**

```bash
git add skills/ib-suite/ib-common/pyproject.toml
git commit -m "chore(ib-common): complete packaging metadata"
```

---

### Task 11: Reconcile CLAUDE.md docs/superpowers wording

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing.
- Produces: CLAUDE.md text that matches the repo's actual tracked state.

- [ ] **Step 1: Fix the §2 line about docs/superpowers**

Current text in `CLAUDE.md` §2 reads:

```text
docs/superpowers/{plans,specs}/         local-only design docs (gitignored, NOT distributed)
```

Replace with:

```text
docs/superpowers/{plans,specs}/         design history (specs + plans), tracked and distributed with the repo
```

- [ ] **Step 2: Fix the §1 "Read on demand" clause**

Current text in `CLAUDE.md` §1 (Project Overview, last bullet) reads:

```text
- Domain knowledge and historical decisions live in `docs/superpowers/`
  (gitignored, local-only). **Read on demand**; do not load them wholesale into
  context, and do not assume they ship with the skill.
```

Replace with:

```text
- Domain knowledge and historical decisions live in `docs/superpowers/`
  (tracked in git as design history). **Read on demand**; do not load them
  wholesale into context. They ship with the repo but are excluded from the
  distributable skill unit (see §11).
```

- [ ] **Step 3: Fix the §11 exclusion list**

Current text in `CLAUDE.md` §11 (Packaging / Distribution) excludes
`docs/superpowers/` from distribution:

```text
- Exclude `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `data/runs/`,
  `.ib-suite/`, `docs/superpowers/`, and the real config/snapshots (all covered by
  `.gitignore`).
```

Replace with:

```text
- Exclude `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `data/runs/`,
  `.ib-suite/`, and the real config/snapshots (all covered by `.gitignore`).
  `docs/superpowers/` is tracked as design history and ships with the repo, but
  is not part of the installable `skills/ib-suite/` skill unit.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: reconcile docs/superpowers wording with tracked state"
```

---

### Task 12: Wire README badges to real CI + community files

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Consumes: `.github/workflows/ci.yml` (workflow name `CI`), `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`.
- Produces: updated badge and Contributing links in both READMEs.

- [ ] **Step 1: Replace the static badge row in `README.md`**

Current first badge line is the static `Agent Skill` badge. Add a live CI badge
as the first badge and keep the rest. The badge block becomes:

```markdown
[![CI](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill-6f42c1)](#installation)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![Read-only](https://img.shields.io/badge/IB%20access-read--only-2ea44f)](#safety--read-only-boundary)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
```

- [ ] **Step 2: Update the Contributing section in `README.md`**

Ensure the Contributing section links to the new files. Replace its body with:

```markdown
Issues and PRs are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
dev setup, the read-only invariant, and commit conventions;
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for community expectations; and
[`SECURITY.md`](SECURITY.md) to report vulnerabilities privately. Run the full
test suite and keep secrets and runtime data (`.ib-suite/`, real `config.yaml`,
live snapshots) out of commits. See [`CLAUDE.md`](CLAUDE.md) for the full
architecture.
```

- [ ] **Step 3: Mirror the badge block in `README.zh-CN.md`**

Apply the same CI badge as Step 1, with the anchor targets kept as the existing
Chinese versions (`#安全与只读边界`), and license badge pointing to `LICENSE`:

```markdown
[![CI](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/luyangkk/ib-suite/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill-6f42c1)](#安装)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![Read-only](https://img.shields.io/badge/IB%20access-read--only-2ea44f)](#安全与只读边界)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
```

- [ ] **Step 4: Update the Contributing section in `README.zh-CN.md`**

Replace its body with:

```markdown
欢迎提 Issue 和 PR。请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 了解开发环境、
只读不变量与提交约定;[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) 了解社区准则;
以及 [`SECURITY.md`](SECURITY.md) 私下报告安全问题。请运行全量测试,并确保敏感信息与
运行时数据(`.ib-suite/`、真实 `config.yaml`、实时快照)不进入提交。完整架构见
[`CLAUDE.md`](CLAUDE.md)。
```

- [ ] **Step 5: Commit**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: wire README badges to CI and community files"
```

---

## Self-Review

**Spec coverage:**
- LICENSE → Task 1 ✅
- CONTRIBUTING → Task 2 ✅
- CODE_OF_CONDUCT → Task 3 ✅
- SECURITY → Task 4 ✅
- CHANGELOG → Task 5 ✅
- .editorconfig → Task 6 ✅
- CI workflow → Task 7 ✅
- Issue templates + config → Task 8 ✅
- PR template → Task 9 ✅
- pyproject metadata → Task 10 ✅
- CLAUDE.md reconciliation → Task 11 ✅
- README badges/links → Task 12 ✅

**Placeholder scan:** No "TBD"/"implement later"; every file has full content. Contact channels intentionally use GitHub advisory (a real mechanism), per the approved spec.

**Consistency:** Repo slug `luyangkk/ib-suite`, MIT/2026/luyangkk, and the CI workflow name `CI` are used identically across LICENSE, pyproject, SECURITY, issue config, and both README badge blocks. The CI badge URL (`actions/workflows/ci.yml/badge.svg`) matches the workflow filename created in Task 7.

**Note on baseline:** Before Task 10, record the current `pytest skills -q` pass count so Steps in Tasks 7 and 10 can assert "unchanged".
