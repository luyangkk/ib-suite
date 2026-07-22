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
