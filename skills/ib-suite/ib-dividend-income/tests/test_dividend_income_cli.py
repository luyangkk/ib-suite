"""Tests for the dividend-income orchestration and command-line boundary."""
from __future__ import annotations

import json
import os
import re
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
    config.parent.mkdir(parents=True, exist_ok=True)
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
    assert result["realized_dividends"][0]["gross"] == 25.0
    assert result["realized_dividends"][0]["quantity"] == 100.0
    assert result["summary"]["realized"]["gross"] == 25.0
    assert result["annual_estimate"]["estimated_base_gross"] == 25.0
    assert result["annual_estimate"]["history_days_covered"] == 212
    assert result["annual_estimate"]["complete_history"] is False
    assert "2026-01-01" in result["coverage_note"]
    assert "2026-07-31" in result["coverage_note"]
    assert result["run_id"] == "test-run"


def test_orchestration_future_end_uses_today_for_annual_history(
    tmp_path: Path, sample_xml: str
) -> None:
    """Future expected range uses a strict annual-history window through today."""
    config = _write_config(
        tmp_path,
        query_ids={"340": "QUERY-340", "365": "QUERY-365"},
    )
    calls: list[tuple[str, str]] = []

    def fetcher(token: str, query_id: str) -> str:
        """Record the selected future-range query and return the Flex fixture."""
        calls.append((token, query_id))
        return sample_xml

    result = dividend_income(
        str(config),
        "2026-08-01",
        "2026-08-31",
        fetcher=fetcher,
        today=date(2026, 7, 31),
        run_id="future-range-run",
    )

    assert calls == [("TOKEN-SHOULD-NOT-LEAK", "QUERY-365")]
    assert [line["symbol"] for line in result["expected_dividends"]] == ["SGFUND"]
    assert result["annual_estimate"]["history_days_covered"] == 212
    assert result["annual_estimate"]["complete_history"] is False


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
        run_id="missing-token-run",
    )

    assert result == {
        "status": "setup_required",
        "missing": ["flex.token"],
        "guide": "flex-query-setup.md",
        "run_id": "missing-token-run",
    }
    assert called is False


def test_setup_empty_query_map_returns_stable_guide(tmp_path: Path) -> None:
    """An empty query map yields a structured setup state without fetching."""
    config = _write_config(tmp_path, query_ids={})

    result = dividend_income(
        str(config), "2026-07-01", "2026-07-31",
        fetcher=lambda _token, _query: pytest.fail("fetcher must not be called"),
        today=date(2026, 7, 31),
        run_id="empty-map-run",
    )

    assert result == {
        "status": "setup_required",
        "missing": ["flex.query_ids"],
        "guide": "flex-query-setup.md",
        "run_id": "empty-map-run",
    }


def test_coverage_insufficient_window_returns_required_state(tmp_path: Path) -> None:
    """A query pool shorter than the estimate history requests more coverage."""
    config = _write_config(tmp_path, query_ids={"30": "QUERY-30"})

    result = dividend_income(
        str(config), "2026-07-01", "2026-07-31",
        fetcher=lambda _token, _query: pytest.fail("fetcher must not be called"),
        today=date(2026, 7, 31),
        run_id="coverage-run",
    )

    assert result == {
        "status": "coverage_required",
        "missing": ["flex.query_ids.365"],
        "guide": "flex-query-setup.md",
        "run_id": "coverage-run",
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
        run_id="schema-run",
    )

    assert result["status"] == "query_update_required"
    assert result["guide"] == "flex-query-setup.md"
    assert result["run_id"] == "schema-run"
    assert result["missing"] == [
        "CashTransactions",
        "ChangeInDividendAccruals",
        "OpenDividendAccruals",
        "OpenPositions",
        "FinancialInstrumentInformation",
    ]
    assert "U1234567" not in json.dumps(result)


def test_setup_blank_numeric_query_id_does_not_fetch(tmp_path: Path) -> None:
    """A blank numeric Query ID is unconfigured and never reaches the fetcher."""
    config = _write_config(tmp_path, query_ids={"365": "   "})

    result = dividend_income(
        str(config),
        "2026-07-01",
        "2026-07-31",
        fetcher=lambda _token, _query: pytest.fail("fetcher must not be called"),
        today=date(2026, 7, 31),
        run_id="blank-query-run",
    )

    assert result == {
        "status": "setup_required",
        "missing": ["flex.query_ids"],
        "guide": "flex-query-setup.md",
        "run_id": "blank-query-run",
    }


def _run_cli(
    config: Path,
    fixture: Path,
    *,
    log_level: str = "INFO",
    error_message: str | None = None,
    failure_kind: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run the CLI boundary in a child interpreter with an injected fetcher."""
    launcher = """
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
sys.path.insert(0, sys.argv.pop(1))
import dividend_income as cli
fixture = Path(sys.argv.pop(1))
error_message = sys.argv.pop(1)
failure_kind = sys.argv.pop(1)
class FixedDate(cli.date):
    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2026, 7, 31)
cli.date = FixedDate
def fetcher(token: str, query_id: str) -> str:
    if failure_kind == "request":
        raise requests.RequestException(error_message)
    if failure_kind == "parse":
        raise ET.ParseError(error_message)
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
        failure_kind,
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
    assert "event=association_completed" in completed.stderr
    assert "matched_count=1" in completed.stderr
    assert "unmatched_count=0" in completed.stderr
    assert "event=calculation_completed" in completed.stderr
    assert "history_days_covered=212" in completed.stderr
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
    account = "MASTER-ABC-999"
    config = _write_config(tmp_path, token=token, query_ids={"365": query_id})
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"
    message = (
        f"accountId={account} Reference Code {reference} "
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


@pytest.mark.parametrize("failure_kind", ["request", "parse"])
def test_cli_retrieval_boundary_failures_are_one_safe_json_object(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    """Network and malformed-response failures use the retrieval error contract."""
    token = "TOKEN-SHOULD-NOT-LEAK"
    query_id = "QUERY-SHOULD-NOT-LEAK"
    account = "INSTITUTIONAL-ACCOUNT-77"
    config = _write_config(tmp_path, token=token, query_ids={"365": query_id})
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"
    error_message = (
        f"account={account} https://example.invalid/report?t={token}&q={query_id}"
    )

    completed = _run_cli(
        config,
        fixture,
        error_message=error_message,
        failure_kind=failure_kind,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert completed.stdout.count("\n") == 1
    assert payload["status"] == "error"
    assert payload["message"] == (
        "Flex report retrieval failed; verify setup and service status"
    )
    assert "invalid_local_input" not in completed.stderr
    for secret in (token, query_id, account, "https://", "?t=", "&q="):
        assert secret not in completed.stdout
        assert secret not in completed.stderr


def test_cli_malformed_query_map_is_structured_and_never_leaks(
    tmp_path: Path,
) -> None:
    """Malformed query windows return safe setup metadata without raw input."""
    token = "TOKEN-SHOULD-NOT-LEAK"
    sentinel = "MALFORMED-QUERY-SENTINEL"
    config = _write_config(tmp_path, token=token, query_ids={"bad": sentinel})
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"

    completed = _run_cli(config, fixture)

    payload = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert payload["status"] == "setup_required"
    assert payload["missing"] == ["flex.query_ids"]
    assert payload["guide"] == "flex-query-setup.md"
    assert payload["message"] == "Flex configuration is invalid"
    assert re.fullmatch(r"[0-9a-f]{32}", payload["run_id"])
    assert f"run_id={payload['run_id']}" in completed.stderr
    for secret in (token, sentinel):
        assert secret not in completed.stdout
        assert secret not in completed.stderr


def test_cli_every_payload_correlates_stdout_and_stderr_run_id(
    tmp_path: Path,
) -> None:
    """Success and each representative failure share one generated run ID."""
    fixture = Path(__file__).parent / "fixtures" / "flex_dividend_income_sample.xml"
    missing_section = tmp_path / "missing-section.xml"
    missing_section.write_text(
        "<FlexQueryResponse><FlexStatements><FlexStatement>"
        '<AccountInformation accountId="U1234567" currency="USD"/>'
        "</FlexStatement></FlexStatements></FlexQueryResponse>",
        encoding="utf-8",
    )
    invalid_xml = tmp_path / "invalid.xml"
    invalid_xml.write_text("not XML", encoding="utf-8")
    success_config = _write_config(tmp_path / "success", query_ids={"365": "Q1"})
    setup_config = _write_config(tmp_path / "setup", token=None)
    coverage_config = _write_config(tmp_path / "coverage", query_ids={"30": "Q30"})
    schema_config = _write_config(tmp_path / "schema", query_ids={"365": "Q365"})
    processing_config = _write_config(
        tmp_path / "processing", query_ids={"365": "Q365"}
    )
    service_config = _write_config(
        tmp_path / "service", query_ids={"365": "Q365"}
    )
    cases = [
        ("success", _run_cli(success_config, fixture)),
        ("setup_required", _run_cli(setup_config, fixture)),
        ("coverage_required", _run_cli(coverage_config, fixture)),
        ("query_update_required", _run_cli(schema_config, missing_section)),
        ("error", _run_cli(processing_config, invalid_xml)),
        (
            "error",
            _run_cli(service_config, fixture, error_message="safe service failure"),
        ),
    ]

    for expected_status, completed in cases:
        payload = json.loads(completed.stdout)
        assert payload.get("status", "success") == expected_status
        assert re.fullmatch(r"[0-9a-f]{32}", payload["run_id"])
        assert completed.stderr.count(f"run_id={payload['run_id']}") >= 1
        logged_ids = set(re.findall(r"run_id=([0-9a-f]{32})", completed.stderr))
        assert logged_ids == {payload["run_id"]}
        assert completed.stdout.count("\n") == 1


def test_cli_module_does_not_import_gateway_client() -> None:
    """The read-only dividend CLI never imports Gateway or order clients."""
    source = (SCRIPTS_DIR / "dividend_income.py").read_text(encoding="utf-8")
    assert "ib_async" not in source
    assert "ib_sync" not in source
    assert "place" + "Order" not in source
