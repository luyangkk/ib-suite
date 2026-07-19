"""Read-only IBKR Flex dividend-income command-line entrypoint."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ib-gateway" / "scripts"))

from flex_fetch import (  # noqa: E402
    FlexQuerySchemaError,
    FlexServiceError,
    fetch_flex_report,
    parse_flex_dividend_dataset,
)
from ib_common.config import load_config  # noqa: E402
from ib_common.dividend_income import build_dividend_income_report  # noqa: E402
from ib_common.flex import parse_iso_date, select_numeric_window  # noqa: E402

LOGGER = logging.getLogger("ib_dividend_income")
GUIDE = "flex-query-setup.md"


def _state(status: str, missing: list[str]) -> dict[str, object]:
    """Build a stable JSON-safe setup state containing only schema names."""
    return {"status": status, "missing": missing, "guide": GUIDE}


def _sanitize(message: str, sensitive_values: tuple[str, ...] = ()) -> str:
    """Remove credentials, identifiers, URLs, parameters, and XML from log text."""
    normalized = " ".join(message.split())
    if "<" in normalized or ">" in normalized:
        return "sensitive response details redacted"
    for value in sorted(filter(None, sensitive_values), key=len, reverse=True):
        normalized = normalized.replace(value, "[REDACTED]")
    normalized = re.sub(r"https?://\S+", "[REDACTED_URL]", normalized)
    normalized = re.sub(
        r"(?i)\b(?:t|q)=[^&\s]+", "[REDACTED_PARAMETER]", normalized
    )
    normalized = re.sub(
        r"(?i)\b(?:reference[ _]?code)(?:\s*[:=]\s*|\s+)[^\s&,;]+",
        "reference_code=[REDACTED]",
        normalized,
    )
    normalized = re.sub(
        r"\b(?:DU|U|D|F)\d{4,}\b", "[REDACTED_ACCOUNT]", normalized
    )
    return normalized


def _log(
    level: int,
    event: str,
    *,
    run_id: str,
    fields: dict[str, object] | None = None,
) -> None:
    """Write one sanitized structured event without serializing report rows."""
    safe_fields = fields or {}
    suffix = " ".join(
        f"{key}={_sanitize(str(value))}" for key, value in safe_fields.items()
    )
    message = f"event={event} run_id={_sanitize(run_id)}"
    if suffix:
        message = f"{message} {suffix}"
    LOGGER.log(level, message)


def dividend_income(
    config_path: str,
    start: str,
    end: str,
    fetcher: Callable[[str, str], str] = fetch_flex_report,
    today: date | None = None,
    run_id: str | None = None,
) -> dict:
    """Fetch one strict Flex window and return a JSON-safe dividend report."""
    started = time.monotonic()
    resolved_run_id = run_id or uuid.uuid4().hex
    _log(logging.INFO, "run_started", run_id=resolved_run_id)

    cfg = load_config(config_path)
    if not cfg.flex.token:
        _log(logging.INFO, "setup_required", run_id=resolved_run_id)
        return _state("setup_required", ["flex.token"])

    numeric_windows = {
        key: query_id
        for key, query_id in cfg.flex.query_ids.items()
        if key.isdigit()
    }
    if not numeric_windows:
        _log(logging.INFO, "setup_required", run_id=resolved_run_id)
        return _state("setup_required", ["flex.query_ids"])

    start_date = parse_iso_date(start)
    end_date = parse_iso_date(end)
    if start_date > end_date:
        raise ValueError("--start-date must be on or before --end-date")
    resolved_today = today or date.today()
    required_start = min(start_date, end_date - timedelta(days=364))
    required_days = (resolved_today - required_start).days + 1
    try:
        window, query_id, _ = select_numeric_window(
            numeric_windows,
            required_start,
            resolved_today,
            allow_partial=False,
        )
    except ValueError:
        _log(
            logging.INFO,
            "coverage_required",
            run_id=resolved_run_id,
            fields={"required_days": required_days},
        )
        return _state("coverage_required", [f"flex.query_ids.{required_days}"])

    _log(
        logging.INFO,
        "window_selected",
        run_id=resolved_run_id,
        fields={"window": window},
    )
    try:
        xml_text = fetcher(cfg.flex.token, query_id)
        dataset = parse_flex_dividend_dataset(xml_text)
    except FlexQuerySchemaError as exc:
        missing = exc.missing_sections + exc.missing_fields
        _log(
            logging.INFO,
            "query_update_required",
            run_id=resolved_run_id,
            fields={"missing_count": len(missing)},
        )
        return _state("query_update_required", missing)
    except FlexServiceError as exc:
        safe_error = _sanitize(str(exc), (cfg.flex.token, query_id))
        _log(
            logging.ERROR,
            "flex_service_error",
            run_id=resolved_run_id,
            fields={"error": safe_error},
        )
        return {
            "status": "error",
            "message": "Flex report retrieval failed; verify setup and service status",
        }
    except (RuntimeError, ValueError) as exc:
        safe_error = _sanitize(str(exc), (cfg.flex.token, query_id))
        _log(
            logging.ERROR,
            "flex_processing_error",
            run_id=resolved_run_id,
            fields={"error": safe_error},
        )
        return {
            "status": "error",
            "message": "Flex report processing failed; verify query setup",
        }

    _log(
        logging.INFO,
        "sections_parsed",
        run_id=resolved_run_id,
        fields={
            "cash_transactions": len(dataset.cash_transactions),
            "dividend_accruals": len(dataset.dividend_accruals),
            "open_dividend_accruals": len(dataset.open_dividend_accruals),
            "open_positions": len(dataset.open_positions),
            "instruments": len(dataset.instruments),
        },
    )
    theoretical_start = resolved_today - timedelta(days=int(window) - 1)
    report = build_dividend_income_report(
        dataset,
        start_date,
        end_date,
        history_start_date=theoretical_start,
    ).model_dump(mode="json")
    elapsed_ms = round((time.monotonic() - started) * 1000)
    _log(
        logging.INFO,
        "run_completed",
        run_id=resolved_run_id,
        fields={"elapsed_ms": elapsed_ms},
    )
    return report


def _configure_logging(level_name: str) -> None:
    """Configure one stderr-only handler at the requested verbosity."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(getattr(logging, level_name))
    LOGGER.propagate = False


def main(
    fetcher: Callable[[str, str], str] = fetch_flex_report,
) -> int:
    """Parse CLI flags, print one JSON object, and return a process status."""
    parser = argparse.ArgumentParser(
        description="Read-only IBKR Flex dividend income"
    )
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument(
        "--start-date", required=True, help="inclusive YYYY-MM-DD start date"
    )
    parser.add_argument(
        "--end-date", required=True, help="inclusive YYYY-MM-DD end date"
    )
    parser.add_argument(
        "--log-level",
        choices=("INFO", "DEBUG"),
        default="INFO",
        help="stderr logging verbosity",
    )
    args = parser.parse_args()
    _configure_logging(args.log_level)
    try:
        payload = dividend_income(
            args.config,
            args.start_date,
            args.end_date,
            fetcher=fetcher,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        safe_error = _sanitize(str(exc))
        LOGGER.error("event=cli_error error=%s", safe_error)
        payload = {
            "status": "error",
            "message": "Invalid local configuration or date range",
        }
    print(json.dumps(payload, allow_nan=False))
    return 2 if "status" in payload else 0


if __name__ == "__main__":
    raise SystemExit(main())
