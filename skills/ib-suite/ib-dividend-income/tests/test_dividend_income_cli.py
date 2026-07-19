"""Tests for the dividend-income orchestration and command-line boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
IB_SUITE_DIR = SKILL_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dividend_income import dividend_income


@pytest.fixture
def sample_xml() -> str:
    """Return the complete dividend Flex fixture as text."""
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"
    return fixture.read_text(encoding="utf-8")


def _write_config(
    tmp_path: Path,
    *,
    token: str | None = "TOKEN-SHOULD-NOT-LEAK",
    query_ids: dict[str, str] | None = None,
) -> Path:
    """Write a focused local configuration and return its path."""
    flex: dict[str, Any] = {
        "query_ids": (
            {"365": "QUERY-SECRET-365"} if query_ids is None else query_ids
        )
    }
    if token is not None:
        flex["token"] = token
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"flex": flex}), encoding="utf-8")
    return config


def test_orchestration_fetches_once_with_smallest_estimate_window(
    tmp_path: Path, sample_xml: str
) -> None:
    """One Flex request uses the smallest window covering request and estimate."""
    config = _write_config(
        tmp_path,
        query_ids={"30": "QUERY-30", "365": "QUERY-365", "730": "QUERY-730"},
    )
    calls: list[tuple[str, str]] = []

    def fetcher(token: str, query_id: str) -> str:
        """Record one injected Flex fetch and return the fixture."""
        calls.append((token, query_id))
        return sample_xml

    result = dividend_income(
        str(config),
        "2026-05-01",
        "2026-07-31",
        fetcher=fetcher,
        today=date(2026, 7, 31),
        run_id="test-run",
    )

    assert calls == [("TOKEN-SHOULD-NOT-LEAK", "QUERY-365")]
    assert json.loads(json.dumps(result)) == result
    assert result["start_date"] == "2026-05-01"
    assert result["end_date"] == "2026-07-31"
    assert result["annual_estimate"]["history_days_covered"] == 365


def test_setup_missing_token_returns_stable_guide(tmp_path: Path) -> None:
    """A missing token yields a structured setup state without fetching."""
    config = _write_config(tmp_path, token=None)
    called = False

    def fetcher(token: str, query_id: str) -> str:
        """Fail the test if a setup failure reaches the network boundary."""
        nonlocal called
        called = True
        raise AssertionError("fetcher must not be called")

    result = dividend_income(
        str(config), "2026-07-01", "2026-07-31", fetcher=fetcher,
        today=date(2026, 7, 31),
    )

    assert result == {
        "status": "setup_required",
        "missing": ["flex.token"],
        "guide": "flex-query-setup.md",
    }
    assert called is False


def test_setup_empty_query_map_returns_stable_guide(tmp_path: Path) -> None:
    """An empty query map yields a structured setup state without fetching."""
    config = _write_config(tmp_path, query_ids={})

    result = dividend_income(
        str(config), "2026-07-01", "2026-07-31",
        fetcher=lambda _token, _query: pytest.fail("fetcher must not be called"),
        today=date(2026, 7, 31),
    )

    assert result == {
        "status": "setup_required",
        "missing": ["flex.query_ids"],
        "guide": "flex-query-setup.md",
    }


def test_coverage_insufficient_window_returns_required_state(tmp_path: Path) -> None:
    """A query pool shorter than the estimate history requests more coverage."""
    config = _write_config(tmp_path, query_ids={"30": "QUERY-30"})

    result = dividend_income(
        str(config), "2026-07-01", "2026-07-31",
        fetcher=lambda _token, _query: pytest.fail("fetcher must not be called"),
        today=date(2026, 7, 31),
    )

    assert result == {
        "status": "coverage_required",
        "missing": ["flex.query_ids.365"],
        "guide": "flex-query-setup.md",
    }


def test_query_update_missing_section_returns_schema_names(
    tmp_path: Path,
) -> None:
    """An omitted Flex section produces a structured query-update state."""
    config = _write_config(tmp_path)
    xml = """<FlexQueryResponse><FlexStatements><FlexStatement>
        <AccountInformation accountId="U1234567" currency="USD"/>
        </FlexStatement></FlexStatements></FlexQueryResponse>"""

    result = dividend_income(
        str(config), "2026-07-01", "2026-07-31",
        fetcher=lambda _token, _query: xml,
        today=date(2026, 7, 31),
    )

    assert result["status"] == "query_update_required"
    assert result["guide"] == "flex-query-setup.md"
    assert result["missing"] == [
        "CashTransactions",
        "ChangeInDividendAccruals",
        "OpenDividendAccruals",
        "OpenPositions",
        "FinancialInstrumentInformation",
    ]
    assert "U1234567" not in json.dumps(result)


def _run_cli(
    config: Path,
    fixture: Path,
    *,
    log_level: str = "INFO",
    error_message: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI boundary in a child interpreter with an injected fetcher."""
    launcher = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv.pop(1))
import dividend_income as cli
fixture = Path(sys.argv.pop(1))
error_message = sys.argv.pop(1)
class FixedDate(cli.date):
    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2026, 7, 31)
cli.date = FixedDate
def fetcher(token: str, query_id: str) -> str:
    if error_message:
        raise cli.FlexServiceError("1012", error_message)
    return fixture.read_text(encoding="utf-8")
raise SystemExit(cli.main(fetcher=fetcher))
"""
    args = [
        sys.executable,
        "-c",
        launcher,
        str(SCRIPTS_DIR),
        str(fixture),
        error_message or "",
        "--config",
        str(config),
        "--start-date",
        "2026-05-01",
        "--end-date",
        "2026-07-31",
        "--log-level",
        log_level,
    ]
    environment = os.environ.copy()
    python_path = str(IB_SUITE_DIR / "ib-common")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [python_path, environment.get("PYTHONPATH", "")])
    )
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


@pytest.mark.parametrize("log_level", ["INFO", "DEBUG"])
def test_cli_stdout_is_one_json_object_and_logs_are_safe(
    tmp_path: Path, log_level: str
) -> None:
    """Success emits one JSON object while operational metadata stays safe."""
    token = "TOKEN-SHOULD-NOT-LEAK"
    query_id = "QUERY-SHOULD-NOT-LEAK"
    config = _write_config(tmp_path, token=token, query_ids={"365": query_id})
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"

    completed = _run_cli(config, fixture, log_level=log_level)

    assert completed.returncode == 0
    assert isinstance(json.loads(completed.stdout), dict)
    assert completed.stdout.count("\n") == 1
    assert "run_id=" in completed.stderr
    assert "window=365" in completed.stderr
    assert "cash_transactions=2" in completed.stderr
    assert "elapsed_ms=" in completed.stderr
    forbidden = [token, query_id, "U0000000", "<FlexQueryResponse", "265598"]
    for secret in forbidden:
        assert secret not in completed.stdout
        assert secret not in completed.stderr


def test_cli_flex_error_is_nonzero_json_and_sanitized(tmp_path: Path) -> None:
    """A service error remains structured and redacts credentials and URLs."""
    token = "TOKEN-SHOULD-NOT-LEAK"
    query_id = "QUERY-SHOULD-NOT-LEAK"
    reference = "REFERENCE-SHOULD-NOT-LEAK"
    account = "U1234567"
    config = _write_config(tmp_path, token=token, query_ids={"365": query_id})
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"
    message = (
        f"account {account} Reference Code {reference} "
        f"https://example.invalid/report?t={token}&q={query_id}"
    )

    completed = _run_cli(
        config, fixture, log_level="DEBUG", error_message=message
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert payload["status"] == "error"
    assert completed.stdout.count("\n") == 1
    for secret in (token, query_id, reference, account, "https://", "?t=", "&q="):
        assert secret not in completed.stdout
        assert secret not in completed.stderr


def test_cli_module_does_not_import_gateway_client() -> None:
    """The read-only dividend CLI never imports Gateway or order clients."""
    source = (SCRIPTS_DIR / "dividend_income.py").read_text(encoding="utf-8")
    assert "ib_async" not in source
    assert "ib_sync" not in source
    assert "placeOrder" not in source
