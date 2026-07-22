# Pre-release open-source overhaul — design

- **Date:** 2026-07-22
- **Status:** approved (pending spec review)
- **Scope owner:** ib-suite maintainers

## 1. Goal

Bring the `ib-suite` repository up to standard GitHub open-source project
conventions **before publishing**, without touching any business code, schema,
or skill behavior. The suite already ships working skills, tests, and bilingual
READMEs; this overhaul adds the community/governance/automation scaffolding a
public repo is expected to have.

Success criteria:

- A visitor landing on the GitHub repo finds a license, contribution guide,
  security policy, code of conduct, changelog, CI status, and issue/PR templates.
- `pytest skills -q` runs in CI on every push/PR (Ubuntu, Python 3.11 + 3.12).
- No business logic, schema, or skill behavior changes.
- No secrets or runtime data enter version control.
- Existing docs no longer contradict the repo's actual tracked state.

## 2. Non-goals (hard boundaries)

- **No business-code changes.** Scripts, `ib_common`, `ib_analyst`, schema, and
  thresholds are untouched.
- **No lint/format toolchain.** User chose the "full standard suite" tier, not
  the "suite + code-quality toolchain" tier. `ruff` / `pre-commit` are explicitly
  out of scope for this pass.
- **No directory restructuring**, no skill renames, no behavior changes.
- **No new license beyond MIT.** No remote push (repo has no remote yet).
- **The read-only invariant stands:** nothing added here can place, modify, or
  cancel an order, and no credential is committed or printed.

## 3. Decisions (confirmed)

- **License:** MIT, year 2026, holder `luyangkk`. README already declares MIT.
- **CI:** GitHub Actions on `ubuntu-latest`, matrix Python `3.11` and `3.12`
  (3.13 excluded — scientific-stack wheels not uniformly available yet). Steps:
  checkout → set up Python → `bash skills/ib-suite/scripts/setup_venv.sh` →
  `skills/ib-suite/.venv/bin/python -m pytest skills -q`.
- **SECURITY.md contact:** report via GitHub private security advisory (no
  personal email exposed).
- **Code of Conduct:** Contributor Covenant v2.1 with a placeholder contact.
- **docs/superpowers contradiction:** keep the files tracked (they ship as design
  history); update CLAUDE.md wording to match, rather than removing them.
- CI badge shows "no status" until the first push to GitHub triggers Actions;
  accepted.

## 4. Work items

### 4.1 New files — root

| File | Content | Source of truth |
|---|---|---|
| `LICENSE` | MIT text, 2026, `luyangkk` | README MIT declaration |
| `CONTRIBUTING.md` | Dev flow distilled from CLAUDE.md: `setup_venv.sh` → TDD → `pytest`; read-only invariant; `type(scope): ...` commit style; never commit `.ib-suite/` / real `config.yaml` / live snapshots | CLAUDE.md §5–§8, §10 |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 | OSS convention |
| `SECURITY.md` | Read-only boundary, credentials-never-committed stance, private-advisory reporting flow, supported versions | Project security posture |
| `CHANGELOG.md` | Keep a Changelog format; `Unreleased` + initial `0.1.0` entry | Version traceability |
| `.editorconfig` | 4-space Python, 2-space YAML/JSON, LF, final newline, trim trailing whitespace | Cross-editor consistency |

### 4.2 New files — `.github/`

| File | Content |
|---|---|
| `.github/workflows/ci.yml` | Ubuntu, matrix 3.11/3.12; bootstrap venv + `pytest skills -q`; triggers on push + pull_request |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | Structured form; includes "confirms read-only / no credentials leaked" acknowledgement |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | Structured form; problem/proposal/scope-boundary fields |
| `.github/ISSUE_TEMPLATE/config.yml` | Disable blank issues, point to discussions/security policy |
| `.github/PULL_REQUEST_TEMPLATE.md` | Checklist: tests pass, read-only boundary respected, no sensitive data, docs reconciled |

### 4.3 Modified files

| File | Change |
|---|---|
| `skills/ib-suite/ib-common/pyproject.toml` | Add `license`, `authors`, `readme`, `keywords`, `classifiers`, `[project.urls]` (Homepage/Repository/Issues). No dependency changes. |
| `CLAUDE.md` | §1 and §11 wording about `docs/superpowers/` — change "gitignored / local-only / NOT distributed" to reflect that these design docs are tracked and ship as project design history. |
| `README.md` / `README.zh-CN.md` | Point the CI badge at the real workflow; confirm license badge links to `LICENSE`; ensure the Contributing section references `CONTRIBUTING.md` / `SECURITY.md`. |

## 5. Verification

- `git ls-files` confirms no `.ib-suite/`, real `config.yaml`, `.venv/`, or live
  snapshot is tracked (only desensitized test fixtures remain, as today).
- `skills/ib-suite/.venv/bin/python -m pytest skills -q` still passes locally
  (baseline count recorded before/after — expected unchanged, since no code
  changes).
- YAML files (`ci.yml`, issue templates) parse without error.
- Badges in both READMEs resolve to the new workflow / `LICENSE` paths.
- CLAUDE.md no longer claims `docs/superpowers/` is gitignored/undistributed.

## 6. Residual risk

- CI badge stays "no status" until first GitHub push — cosmetic, expected.
- `pyproject.toml` URLs use the `luyangkk/ib-suite` repo path from the README;
  if the final repo slug differs, URLs need a one-line update.
- Contributor Covenant and SECURITY.md carry a placeholder contact until a real
  reporting channel is chosen.
