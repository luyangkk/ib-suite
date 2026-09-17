"""Contract tests for the portable dividend-income reference."""
from __future__ import annotations

from pathlib import Path


SUITE_ROOT = Path(__file__).resolve().parents[2]
REFERENCE = SUITE_ROOT / "references" / "ib-dividend-income.md"
GUIDE = SUITE_ROOT / "references" / "ib-dividend-income-flex-query-setup.md"
PARENT = SUITE_ROOT / "SKILL.md"


def test_dividend_reference_uses_portable_workspace_paths() -> None:
    text = REFERENCE.read_text(encoding="utf-8")

    assert not text.startswith("---\n")
    assert "{baseDir}" not in text
    assert "$SKILL_ROOT/ib-dividend-income/scripts/dividend_income.py" in text
    assert "$WORKSPACE_ROOT/.ib-suite/venv/bin/python" in text
    assert "$WORKSPACE_ROOT/.ib-suite/config.yaml" in text
    assert "never uses Gateway, market data, or orders" in text


def test_dividend_setup_stays_read_only_and_token_safe() -> None:
    text = GUIDE.read_text(encoding="utf-8")

    for phrase in (
        "Client Portal",
        "Flex Web Service",
        "--token-stdin",
        "explicit confirmation",
        "do not place, modify, or cancel orders",
        "$SKILL_ROOT/ib-trade-history/scripts/configure_flex.py",
    ):
        assert phrase in text
    assert "{baseDir}" not in text


def test_parent_routes_dividend_requests_to_the_reference() -> None:
    text = PARENT.read_text(encoding="utf-8")

    assert text.count("references/ib-dividend-income.md") == 1
    assert text.count("references/ib-dividend-income-flex-query-setup.md") == 1
