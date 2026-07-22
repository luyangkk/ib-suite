"""Contract tests for the OpenClaw dividend-income documentation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


SKILL_DIR = Path(__file__).resolve().parents[1]
SUITE_DIR = SKILL_DIR.parent
SKILL_PATH = SKILL_DIR / "SKILL.md"
GUIDE_PATH = SKILL_DIR / "flex-query-setup.md"
INDEX_PATH = SUITE_DIR / "SKILL.md"
TRADE_SKILL_PATH = SUITE_DIR / "ib-trade-history" / "SKILL.md"


def _frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse one Markdown file's YAML frontmatter and return its body."""
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, flags=re.DOTALL)
    assert match is not None, f"{path} must contain YAML frontmatter"
    metadata = YAML(typ="safe").load(match.group(1))
    assert isinstance(metadata, dict)
    return metadata, match.group(2)


def test_skill_frontmatter_matches_openclaw_contract() -> None:
    """The skill stays discoverable so its own Flex onboarding can run."""
    frontmatter, _ = _frontmatter(SKILL_PATH)

    assert frontmatter["name"] == SKILL_DIR.name == "ib-dividend-income"
    assert frontmatter["description"].startswith("Read-only")
    openclaw = frontmatter["metadata"]["openclaw"]
    assert openclaw["requires"]["bins"] == ["python3"]
    assert "config" not in openclaw["requires"]
    assert openclaw["os"] == ["darwin", "linux"]


def test_skill_command_is_portable_and_date_explicit() -> None:
    """The documented command uses the shared interpreter and two ISO dates."""
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert (
        "{baseDir}/../.venv/bin/python {baseDir}/scripts/dividend_income.py"
        in text
    )
    assert "--start-date" in text
    assert "--end-date" in text
    assert "/ib-dividend-income" in text
    assert "/Users/" not in text
    assert "/home/" not in text


def test_skill_defines_presentation_and_setup_behavior() -> None:
    """The control plane preserves output order, limitations, and safe setup."""
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert text.index("Realized dividends") < text.index("Expected dividends")
    columns = (
        "Symbol | Payment date | Status | Gross | Withholding tax | Fee | Net | "
        "Currency | FX rate to base | Base-currency amount | Quantity | Country"
    )
    assert columns in text
    for phrase in (
        "realized totals",
        "expected totals",
        "currency attribution",
        "country attribution",
        "separate realized and expected attribution",
        "highest-contributing holdings",
        "annual estimate",
        "portfolio dividend yield",
        "coverage_note",
        "data_limitations",
        "null",
        "Chinese",
        "setup_required",
        "coverage_required",
        "query_update_required",
        "{baseDir}/flex-query-setup.md",
        "one item at a time",
        "--token-stdin",
        "--force",
        "explicit confirmation",
    ):
        assert phrase in text


def test_skill_explains_future_expected_and_trailing_history_dates() -> None:
    """Future expected rows stay in range without inflating annual history."""
    text = " ".join(SKILL_PATH.read_text(encoding="utf-8").split()).lower()

    assert "expected rows extend through the requested future end date" in text
    assert "annual trailing history is capped at today" in text
    assert "future calendar days do not count" in text
    assert "history_days_covered" in text


def test_setup_guide_lists_every_required_flex_section_and_field() -> None:
    """The guide enumerates six dividend sections plus compatible Trades."""
    text = GUIDE_PATH.read_text(encoding="utf-8")
    sections = {
        "Account Information": ("accountId", "currency"),
        "Cash Transactions": (
            "accountId", "currency", "assetCategory", "fxRateToBase", "symbol",
            "description", "conid", "underlyingConid", "underlyingSymbol",
            "dateTime", "amount", "type", "tradeID", "code",
        ),
        "Change in Dividend Accruals": (
            "accountId", "currency", "assetCategory", "fxRateToBase", "symbol",
            "description", "conid", "date", "exDate", "payDate", "quantity",
            "tax", "fee", "grossRate", "grossAmount", "netAmount", "code",
            "reportDate",
        ),
        "Open Dividend Accruals": (
            "accountId", "currency", "assetCategory", "fxRateToBase", "symbol",
            "conid", "exDate", "payDate", "quantity", "tax", "fee",
            "grossRate", "grossAmount", "netAmount", "code",
        ),
        "Open Positions": (
            "accountId", "currency", "assetCategory", "fxRateToBase", "symbol",
            "conid", "reportDate", "position", "multiplier", "markPrice",
            "positionValue", "side", "levelOfDetail",
        ),
        "Financial Instrument Information": (
            "assetCategory", "symbol", "currency", "listingExchange",
            "description", "conid", "isin", "multiplier", "subCategory",
        ),
        "Trades": (
            "dateTime", "tradeID", "symbol", "buySell", "quantity",
            "tradePrice", "ibCommission", "currency",
            "ibCommissionCurrency", "multiplier", "orderType", "exchange",
            "openCloseIndicator", "fifoPnlRealized", "fxRateToBase",
        ),
    }

    for section, fields in sections.items():
        heading = f"### {section}"
        assert heading in text
        section_text = text.split(heading, maxsplit=1)[1].split("\n### ", maxsplit=1)[0]
        for field in fields:
            assert f"`{field}`" in section_text


def test_setup_guide_covers_safe_registration_and_remote_validation() -> None:
    """The setup path covers IBKR creation, credentials, validation, and repair."""
    text = GUIDE_PATH.read_text(encoding="utf-8")

    for phrase in (
        "Client Portal",
        "Performance & Reports",
        "Flex Queries",
        "Activity Flex Query",
        "XML",
        "yyyy-MM-dd",
        "7",
        "30",
        "90",
        "365",
        "mtd",
        "ytd",
        "Query ID",
        "Flex Web Service",
        "token",
        "--token-stdin",
        "--window",
        "--force",
        "explicit confirmation",
        "rotate",
        "Troubleshooting",
        "does not prove the remote query is correct",
    ):
        assert phrase in text


def test_setup_guide_explains_independent_registration_and_coverage() -> None:
    """Window guidance separates the dividend map from numeric coverage needs."""
    text = " ".join(GUIDE_PATH.read_text(encoding="utf-8").split()).lower()

    assert "six dividend sections" in text
    assert "trades" in text
    assert "register independent query ids" in text
    assert "7/30/90" in text
    assert "short-range dividend requests" in text
    assert "dividend income generally requires a `365`" in text
    assert "older historical requested ranges" in text
    assert "coverage_required" in text


def test_trade_history_setup_keeps_tokens_out_of_command_arguments() -> None:
    """Trade-history setup passes tokens only through execution-tool stdin."""
    raw_text = TRADE_SKILL_PATH.read_text(encoding="utf-8")
    text = " ".join(raw_text.split()).lower()

    assert "--token '<provided-token>'" not in raw_text
    assert re.search(r"--token(?:\s|=)", raw_text) is None
    assert "--token-stdin" in text
    assert "execution tool" in text
    assert "stdin" in text
    assert "never place the token in argv or command text" in text
    assert "explicit confirmation" in text
    assert "--force" in text


def test_docs_preserve_the_flex_only_read_only_boundary() -> None:
    """Both documents forbid Gateway, market-data, order, and persistence use."""
    for path in (SKILL_PATH, GUIDE_PATH):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "do not start IB Gateway" in text
        assert "do not request market data" in text
        assert "do not place, modify, or cancel orders" in text
        assert "do not persist account data" in text


def test_suite_index_names_routes_and_invokes_dividend_income() -> None:
    """The suite router exposes the new skill in discovery and direct commands."""
    text = INDEX_PATH.read_text(encoding="utf-8")

    assert "[ib-dividend-income]({baseDir}/ib-dividend-income)" in text
    assert "`ib-dividend-income` → `/ib-dividend-income`" in text
    assert "ib-dividend-income/scripts/dividend_income.py" in text
    assert "ib-dividend-income/" in text
    assert "Flex-only" in text
