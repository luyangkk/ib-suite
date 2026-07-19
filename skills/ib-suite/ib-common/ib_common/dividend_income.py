"""Pure reconciliation and calculation helpers for Flex dividend income."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Literal, TypeAlias

from ib_common.schema import (
    AnnualDividendEstimate,
    AnnualDividendHolding,
    DividendContribution,
    DividendIncomeLine,
    DividendIncomeReport,
    DividendIncomeSummary,
    DividendTotals,
    FlexCashTransaction,
    FlexDividendAccrual,
    FlexDividendDataset,
    FlexInstrument,
    FlexOpenPosition,
)


_EventKey: TypeAlias = tuple[str, str, str, date, date]
_CashEventKey: TypeAlias = tuple[str, str, str, date]
_MATCH_TOLERANCE_DAYS = 3
_EXCHANGE_COUNTRIES = {
    "AEB": "NL",
    "AMEX": "US",
    "ARCA": "US",
    "ASX": "AU",
    "BATS": "US",
    "EBS": "CH",
    "FWB": "DE",
    "HKEX": "HK",
    "IBIS": "DE",
    "IBIS2": "DE",
    "IEX": "US",
    "LSE": "GB",
    "NASDAQ": "US",
    "NASDAQCM": "US",
    "NASDAQGM": "US",
    "NASDAQGS": "US",
    "NYSE": "US",
    "NYSEARCA": "US",
    "NYSEMKT": "US",
    "SEHK": "HK",
    "SGX": "SG",
    "SIX": "CH",
    "TSEJ": "JP",
    "TSX": "CA",
    "TSXV": "CA",
    "XETRA": "DE",
}


def _normalized_symbol(symbol: str) -> str:
    """Normalize punctuation, whitespace, and case for deterministic fallback."""
    return "".join(character for character in symbol.upper() if character.isalnum())


def listing_country(exchange: str, isin: str) -> str:
    """Return a primary listing-market country, with absent-exchange ISIN fallback."""
    normalized_exchange = exchange.strip().upper()
    if normalized_exchange:
        return _EXCHANGE_COUNTRIES.get(normalized_exchange, "UNKNOWN")
    normalized_isin = isin.strip().upper()
    if len(normalized_isin) == 12 and normalized_isin[:2].isalpha():
        return normalized_isin[:2]
    return "UNKNOWN"


def _event_key(accrual: FlexDividendAccrual) -> _EventKey:
    """Return the preferred conid event key or its symbol fallback key."""
    identity = (
        f"CONID:{accrual.conid}"
        if accrual.conid
        else f"SYMBOL:{_normalized_symbol(accrual.symbol)}"
    )
    return (
        accrual.account_id,
        identity,
        accrual.currency.upper(),
        accrual.ex_date,
        accrual.pay_date,
    )


def _sum_optional(
    rows: list[FlexDividendAccrual], field_name: str
) -> float | None:
    """Sum one nullable lifecycle amount while preserving all-null input."""
    values = [getattr(row, field_name) for row in rows]
    known = [value for value in values if value is not None]
    return None if not known else sum(known)


def _reduce_accrual_lifecycle(
    rows: list[FlexDividendAccrual],
) -> list[FlexDividendAccrual]:
    """Collapse posting, correction, cancellation, and reversal rows by event."""
    unique_rows: list[FlexDividendAccrual] = []
    seen: set[str] = set()
    for row in rows:
        fingerprint = row.model_dump_json()
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique_rows.append(row)

    groups: dict[_EventKey, list[FlexDividendAccrual]] = defaultdict(list)
    for row in unique_rows:
        groups[_event_key(row)].append(row)

    reduced: list[FlexDividendAccrual] = []
    for event_rows in groups.values():
        representative = event_rows[-1]
        combined = representative.model_copy(
            update={
                "quantity": _sum_optional(event_rows, "quantity"),
                "tax": _sum_optional(event_rows, "tax"),
                "fee": _sum_optional(event_rows, "fee"),
                "gross_rate": _sum_optional(event_rows, "gross_rate"),
                "gross_amount": _sum_optional(event_rows, "gross_amount"),
                "net_amount": _sum_optional(event_rows, "net_amount"),
            }
        )
        positive_event = any(
            value is not None and value > 0
            for value in (
                combined.gross_amount,
                combined.net_amount,
                combined.gross_rate,
            )
        )
        if positive_event:
            reduced.append(combined)
    return reduced


def _best_date_tier(
    cash: FlexCashTransaction,
    candidates: list[FlexDividendAccrual],
) -> list[FlexDividendAccrual]:
    """Prefer exact payment dates, then candidates within three calendar days."""
    payment_date = cash.ts.date()
    exact = [row for row in candidates if row.pay_date == payment_date]
    if exact:
        return exact
    return [
        row
        for row in candidates
        if abs((row.pay_date - payment_date).days) <= _MATCH_TOLERANCE_DAYS
    ]


def _match_accrual(
    cash: FlexCashTransaction,
    accruals: list[FlexDividendAccrual],
) -> tuple[FlexDividendAccrual | None, bool]:
    """Return one best-tier accrual and whether the best tier was ambiguous."""
    common = [
        row
        for row in accruals
        if row.account_id == cash.account_id
        and row.currency.upper() == cash.currency.upper()
    ]
    if cash.conid:
        conid_tier = _best_date_tier(
            cash, [row for row in common if row.conid == cash.conid]
        )
        if conid_tier:
            return (
                (conid_tier[0], False)
                if len(conid_tier) == 1
                else (None, True)
            )

    normalized_cash_symbol = _normalized_symbol(cash.symbol)
    symbol_tier = _best_date_tier(
        cash,
        [
            row
            for row in common
            if _normalized_symbol(row.symbol) == normalized_cash_symbol
            and not (cash.conid and row.conid)
        ],
    )
    if len(symbol_tier) == 1:
        return symbol_tier[0], False
    return None, len(symbol_tier) > 1


def _is_dividend_cash(row: FlexCashTransaction) -> bool:
    """Identify positive dividend cash postings without treating tax as income."""
    return "dividend" in row.transaction_type.casefold() and bool(
        row.amount is not None and row.amount > 0
    )


def _cash_event_key(row: FlexCashTransaction) -> _CashEventKey:
    """Return a deterministic cash lifecycle key using conid or symbol identity."""
    identity = (
        f"CONID:{row.conid}"
        if row.conid
        else f"SYMBOL:{_normalized_symbol(row.symbol)}"
    )
    return (
        row.account_id,
        identity,
        row.currency.upper(),
        row.ts.date(),
    )


def _reduce_dividend_cash_lifecycle(
    rows: list[FlexCashTransaction],
) -> list[FlexCashTransaction]:
    """Net unique signed dividend cash postings and reversals by economic key."""
    unique: list[FlexCashTransaction] = []
    seen: set[str] = set()
    for row in rows:
        if "dividend" not in row.transaction_type.casefold() or row.amount is None:
            continue
        fingerprint = row.model_dump_json()
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(row)
    groups: dict[_CashEventKey, list[FlexCashTransaction]] = defaultdict(list)
    for row in unique:
        groups[_cash_event_key(row)].append(row)
    reduced: list[FlexCashTransaction] = []
    for event_rows in groups.values():
        amount = sum(row.amount for row in event_rows if row.amount is not None)
        if amount > 0:
            reduced.append(event_rows[-1].model_copy(update={"amount": amount}))
    return reduced


def _is_withholding_cash(row: FlexCashTransaction) -> bool:
    """Identify a posted cash-tax deduction that can reconcile withholding."""
    transaction_type = row.transaction_type.casefold()
    return ("withholding" in transaction_type or "tax" in transaction_type) and bool(
        row.amount is not None and row.amount < 0
    )


def _best_cash_date_tier(
    dividend: FlexCashTransaction,
    candidates: list[FlexCashTransaction],
) -> list[FlexCashTransaction]:
    """Prefer same-day tax postings, then the bounded three-day tolerance."""
    payment_date = dividend.ts.date()
    exact = [row for row in candidates if row.ts.date() == payment_date]
    if exact:
        return exact
    return [
        row
        for row in candidates
        if abs((row.ts.date() - payment_date).days) <= _MATCH_TOLERANCE_DAYS
    ]


def _associated_withholding(
    dividend: FlexCashTransaction,
    cash_rows: list[FlexCashTransaction],
) -> float | None:
    """Return one uniquely associated cash-tax deduction, never an arbitrary sum."""
    common = [
        row
        for row in cash_rows
        if _is_withholding_cash(row)
        and row.account_id == dividend.account_id
        and row.currency.upper() == dividend.currency.upper()
    ]
    if dividend.conid:
        conid_tier = _best_cash_date_tier(
            dividend, [row for row in common if row.conid == dividend.conid]
        )
        if conid_tier:
            return (
                abs(conid_tier[0].amount)
                if len(conid_tier) == 1 and conid_tier[0].amount is not None
                else None
            )
    normalized_symbol = _normalized_symbol(dividend.symbol)
    symbol_tier = _best_cash_date_tier(
        dividend,
        [
            row
            for row in common
            if _normalized_symbol(row.symbol) == normalized_symbol
            and not (dividend.conid and row.conid)
        ],
    )
    return (
        abs(symbol_tier[0].amount)
        if len(symbol_tier) == 1 and symbol_tier[0].amount is not None
        else None
    )


def _instrument_for(
    *,
    conid: str | None,
    symbol: str,
    currency: str,
    instruments: list[FlexInstrument],
) -> FlexInstrument | None:
    """Resolve unique instrument metadata by conid, then normalized symbol."""
    if conid:
        conid_matches = [row for row in instruments if row.conid == conid]
        if len(conid_matches) == 1:
            return conid_matches[0]
        if len(conid_matches) > 1:
            return None
    symbol_matches = [
        row
        for row in instruments
        if _normalized_symbol(row.symbol) == _normalized_symbol(symbol)
        and row.currency.upper() == currency.upper()
        and not (conid and row.conid)
    ]
    return symbol_matches[0] if len(symbol_matches) == 1 else None


def _country_for(
    *,
    conid: str | None,
    symbol: str,
    currency: str,
    instruments: list[FlexInstrument],
) -> str:
    """Resolve listing country from uniquely associated instrument metadata."""
    instrument = _instrument_for(
        conid=conid,
        symbol=symbol,
        currency=currency,
        instruments=instruments,
    )
    if instrument is None:
        return "UNKNOWN"
    return listing_country(
        instrument.listing_exchange or "",
        instrument.isin or "",
    )


def _converted(value: float | None, rate: float | None) -> float | None:
    """Convert one known native amount only when Flex supplied an FX rate."""
    return None if value is None or rate is None else value * rate


def _line_from_accrual(
    accrual: FlexDividendAccrual,
    *,
    status: Literal["REALIZED", "EXPECTED"],
    country: str,
) -> DividendIncomeLine:
    """Convert an accrual to one native and nullable base-currency line."""
    withholding_tax = None if accrual.tax is None else abs(accrual.tax)
    fee = None if accrual.fee is None else abs(accrual.fee)
    return DividendIncomeLine(
        symbol=accrual.symbol.strip(),
        payment_date=accrual.pay_date,
        status=status,
        gross=accrual.gross_amount,
        withholding_tax=withholding_tax,
        fee=fee,
        net=accrual.net_amount,
        currency=accrual.currency.upper(),
        fx_rate_to_base=accrual.fx_rate_to_base,
        base_gross=_converted(accrual.gross_amount, accrual.fx_rate_to_base),
        base_withholding_tax=_converted(
            withholding_tax, accrual.fx_rate_to_base
        ),
        base_fee=_converted(fee, accrual.fx_rate_to_base),
        base_net=_converted(accrual.net_amount, accrual.fx_rate_to_base),
        quantity=accrual.quantity,
        country=country,
    )


def _realized_line(
    cash: FlexCashTransaction,
    accrual: FlexDividendAccrual | None,
    *,
    country: str,
    cash_withholding: float | None,
) -> DividendIncomeLine:
    """Convert confirmed dividend cash and optional accrual facts to one line."""
    if accrual is not None:
        rate = (
            accrual.fx_rate_to_base
            if accrual.fx_rate_to_base is not None
            else cash.fx_rate_to_base
        )
        line = _line_from_accrual(
            accrual,
            status="REALIZED",
            country=country,
        )
        withholding_tax = (
            line.withholding_tax
            if line.withholding_tax is not None
            else cash_withholding
        )
        return line.model_copy(
            update={
                "symbol": cash.symbol.strip(),
                "payment_date": cash.ts.date(),
                "fx_rate_to_base": rate,
                "withholding_tax": withholding_tax,
                "base_gross": _converted(line.gross, rate),
                "base_withholding_tax": _converted(
                    withholding_tax, rate
                ),
                "base_fee": _converted(line.fee, rate),
                "base_net": _converted(line.net, rate),
            }
        )
    return DividendIncomeLine(
        symbol=cash.symbol.strip(),
        payment_date=cash.ts.date(),
        status="REALIZED",
        gross=None,
        withholding_tax=cash_withholding,
        fee=None,
        net=cash.amount,
        currency=cash.currency.upper(),
        fx_rate_to_base=cash.fx_rate_to_base,
        base_gross=None,
        base_withholding_tax=_converted(cash_withholding, cash.fx_rate_to_base),
        base_fee=None,
        base_net=_converted(cash.amount, cash.fx_rate_to_base),
        quantity=None,
        country=country,
    )


def _unique_dividend_cash(
    rows: list[FlexCashTransaction],
) -> list[FlexCashTransaction]:
    """Remove byte-for-byte duplicate cash facts before reliability checks."""
    unique: list[FlexCashTransaction] = []
    seen: set[str] = set()
    for row in rows:
        fingerprint = row.model_dump_json()
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(row)
    return unique


def _holding_accruals(
    position: FlexOpenPosition,
    accruals: list[FlexDividendAccrual],
) -> list[FlexDividendAccrual]:
    """Associate trailing rate events with one current holding identity."""
    common = [
        row
        for row in accruals
        if row.account_id == position.account_id
        and row.currency.upper() == position.currency.upper()
    ]
    if position.conid:
        exact = [row for row in common if row.conid == position.conid]
        fallback = [
            row
            for row in common
            if row.conid is None
            and _normalized_symbol(row.symbol) == _normalized_symbol(position.symbol)
        ]
        return exact + fallback
    return [
        row
        for row in common
        if _normalized_symbol(row.symbol) == _normalized_symbol(position.symbol)
    ]


def _effective_tax_rate(
    *,
    symbol: str,
    trailing_start: date,
    end_date: date,
    cash_rows: list[FlexCashTransaction],
    accruals: list[FlexDividendAccrual],
) -> float | None:
    """Calculate tax rate only when every trailing cash event is fully reliable."""
    symbol_cash = _unique_dividend_cash(
        [
            row
            for row in _reduce_dividend_cash_lifecycle(cash_rows)
            if _is_dividend_cash(row)
            and trailing_start <= row.ts.date() <= end_date
            and _normalized_symbol(row.symbol) == _normalized_symbol(symbol)
        ]
    )
    if not symbol_cash:
        return None

    gross_total = 0.0
    tax_total = 0.0
    matched_events: set[_EventKey] = set()
    for cash in symbol_cash:
        accrual, ambiguous = _match_accrual(cash, accruals)
        if ambiguous or accrual is None or accrual.gross_amount is None:
            return None
        if accrual.gross_amount <= 0:
            return None
        tax = (
            abs(accrual.tax)
            if accrual.tax is not None
            else _associated_withholding(cash, cash_rows)
        )
        if tax is None:
            return None
        event_key = _event_key(accrual)
        if event_key in matched_events:
            return None
        matched_events.add(event_key)
        gross_total += accrual.gross_amount
        tax_total += tax

    if gross_total <= 0:
        return None
    return min(1.0, max(0.0, tax_total / gross_total))


def _current_eligible_positions(
    positions: list[FlexOpenPosition],
) -> list[FlexOpenPosition]:
    """Return latest summary-level current long stock and fund positions."""
    candidates = [
        row
        for row in positions
        if row.asset_class.upper() in {"STK", "FUND"}
        and row.level_of_detail.upper() == "SUMMARY"
        and row.side.upper() == "LONG"
        and row.quantity is not None
        and row.quantity > 0
    ]
    if not candidates:
        return []
    latest_by_account: dict[str, date] = {}
    for row in candidates:
        latest_by_account[row.account_id] = max(
            row.report_date,
            latest_by_account.get(row.account_id, row.report_date),
        )
    latest = [
        row
        for row in candidates
        if row.report_date == latest_by_account[row.account_id]
    ]
    unique: list[FlexOpenPosition] = []
    seen: set[str] = set()
    for row in latest:
        fingerprint = row.model_dump_json()
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(row)
    return sorted(unique, key=lambda row: (row.symbol, row.account_id, row.conid or ""))


def _history_days_covered(
    history_start_date: date,
    end_date: date,
) -> int:
    """Measure the available intersection with the inclusive trailing year."""
    trailing_start = end_date - timedelta(days=364)
    overlap_start = max(history_start_date, trailing_start)
    if overlap_start > end_date:
        return 0
    return min(365, (end_date - overlap_start).days + 1)


def _annual_estimate(
    *,
    dataset: FlexDividendDataset,
    accruals: list[FlexDividendAccrual],
    end_date: date,
    history_start_date: date,
    limitations: list[str],
) -> AnnualDividendEstimate:
    """Estimate annual holding income from unique trailing positive accrual rates."""
    trailing_start = end_date - timedelta(days=364)
    window_accruals = [
        row
        for row in accruals
        if trailing_start <= row.ex_date <= end_date
    ]
    trailing_rate_accruals = [
        row
        for row in window_accruals
        if row.gross_rate is not None
        and row.gross_rate > 0
    ]
    positions = _current_eligible_positions(dataset.open_positions)
    holdings: list[AnnualDividendHolding] = []
    denominator_values: list[float] = []
    denominator_complete = True
    for position in positions:
        position_accruals = _holding_accruals(position, trailing_rate_accruals)
        trailing_rate = sum(
            row.gross_rate
            for row in position_accruals
            if row.gross_rate is not None and row.gross_rate > 0
        )
        quantity = position.quantity
        assert quantity is not None
        estimated_gross = trailing_rate * quantity
        effective_tax_rate = _effective_tax_rate(
            symbol=position.symbol,
            trailing_start=trailing_start,
            end_date=end_date,
            cash_rows=dataset.cash_transactions,
            accruals=window_accruals,
        )
        estimated_net = (
            None
            if effective_tax_rate is None
            else estimated_gross * (1.0 - effective_tax_rate)
        )
        holdings.append(
            AnnualDividendHolding(
                symbol=position.symbol,
                quantity=quantity,
                currency=position.currency.upper(),
                fx_rate_to_base=position.fx_rate_to_base,
                trailing_gross_rate=trailing_rate,
                effective_tax_rate=effective_tax_rate,
                estimated_gross=estimated_gross,
                estimated_net=estimated_net,
                base_estimated_gross=_converted(
                    estimated_gross, position.fx_rate_to_base
                ),
                base_estimated_net=_converted(
                    estimated_net, position.fx_rate_to_base
                ),
            )
        )
        if position.position_value is None or position.fx_rate_to_base is None:
            denominator_complete = False
            limitations.append(
                f"Annual yield excludes an unavailable base market value for "
                f"{position.symbol}."
            )
        else:
            denominator_values.append(
                abs(position.position_value) * position.fx_rate_to_base
            )
        if estimated_gross > 0 and effective_tax_rate is None:
            limitations.append(
                f"Annual net estimate for {position.symbol} is unavailable because "
                "trailing realized withholding history is incomplete."
            )

    base_gross_values = [
        holding.base_estimated_gross
        for holding in holdings
        if holding.base_estimated_gross is not None
    ]
    estimated_base_gross = (
        0.0
        if not holdings
        else (sum(base_gross_values) if base_gross_values else None)
    )
    paying_holdings = [holding for holding in holdings if holding.estimated_gross > 0]
    net_complete = all(
        holding.base_estimated_net is not None for holding in paying_holdings
    )
    estimated_base_net = (
        sum(
            holding.base_estimated_net
            for holding in paying_holdings
            if holding.base_estimated_net is not None
        )
        if net_complete
        else None
    )
    eligible_base_market_value = (
        sum(denominator_values) if denominator_complete else None
    )
    numerator_complete = all(
        holding.base_estimated_gross is not None for holding in holdings
    )
    portfolio_yield = (
        estimated_base_gross / eligible_base_market_value
        if numerator_complete
        and estimated_base_gross is not None
        and eligible_base_market_value is not None
        and eligible_base_market_value > 0
        else None
    )
    history_days = _history_days_covered(history_start_date, end_date)
    return AnnualDividendEstimate(
        holdings=holdings,
        estimated_base_gross=estimated_base_gross,
        estimated_base_net=estimated_base_net,
        eligible_base_market_value=eligible_base_market_value,
        portfolio_estimated_gross_yield=portfolio_yield,
        history_days_covered=history_days,
        complete_history=history_days == 365,
    )


def _totals(
    lines: list[DividendIncomeLine],
    *,
    base: bool,
) -> DividendTotals:
    """Aggregate known line components without substituting zero for nulls."""
    if not lines:
        return DividendTotals()
    prefix = "base_" if base else ""

    def component(name: str) -> float | None:
        """Sum known values for one component while retaining all-null state."""
        values = [getattr(line, f"{prefix}{name}") for line in lines]
        known = [value for value in values if value is not None]
        return None if not known else sum(known)

    return DividendTotals(
        gross=component("gross"),
        withholding_tax=component("withholding_tax"),
        fee=component("fee"),
        net=component("net"),
    )


def _group_totals(
    lines: list[DividendIncomeLine],
    *,
    field_name: Literal["currency", "country"],
    base: bool,
) -> dict[str, DividendTotals]:
    """Group dividend totals deterministically by one line attribution field."""
    grouped: dict[str, list[DividendIncomeLine]] = defaultdict(list)
    for line in lines:
        grouped[getattr(line, field_name)].append(line)
    return {
        key: _totals(grouped[key], base=base)
        for key in sorted(grouped)
    }


def _summary(
    realized: list[DividendIncomeLine],
    expected: list[DividendIncomeLine],
) -> DividendIncomeSummary:
    """Create status totals, attribution buckets, and realized contribution rank."""
    all_lines = realized + expected
    country_lines = [line for line in all_lines if line.fx_rate_to_base is not None]
    contributions: dict[str, float] = defaultdict(float)
    for line in realized:
        if line.base_net is not None:
            contributions[line.symbol] += line.base_net
    ranked = sorted(contributions.items(), key=lambda item: (-item[1], item[0]))
    return DividendIncomeSummary(
        realized=_totals(realized, base=True),
        expected=_totals(expected, base=True),
        by_currency=_group_totals(
            all_lines, field_name="currency", base=False
        ),
        by_country=_group_totals(
            country_lines, field_name="country", base=True
        ),
        top_contributors=[
            DividendContribution(symbol=symbol, base_net=base_net)
            for symbol, base_net in ranked
        ],
    )


def build_dividend_income_report(
    dataset: FlexDividendDataset,
    start_date: date,
    end_date: date,
    coverage_note: str | None = None,
    history_start_date: date | None = None,
) -> DividendIncomeReport:
    """Build a deterministic dividend report without I/O or external state.

    ``history_start_date`` is the theoretical inclusive beginning of the selected
    Flex window. It defaults to ``start_date`` for compatibility with callers that
    only need the original four-argument interface.
    """
    effective_history_start = history_start_date or start_date
    accruals = _reduce_accrual_lifecycle(dataset.dividend_accruals)
    dividend_cash = _reduce_dividend_cash_lifecycle(dataset.cash_transactions)
    realized: list[DividendIncomeLine] = []
    limitations: list[str] = []

    in_range_cash = [
        row for row in dividend_cash if start_date <= row.ts.date() <= end_date
    ]
    for cash in in_range_cash:
        accrual, ambiguous = _match_accrual(cash, accruals)
        country = _country_for(
            conid=cash.conid,
            symbol=cash.symbol,
            currency=cash.currency,
            instruments=dataset.instruments,
        )
        cash_withholding = (
            _associated_withholding(cash, dataset.cash_transactions)
            if accrual is None or accrual.tax is None
            else None
        )
        realized.append(
            _realized_line(
                cash,
                accrual,
                country=country,
                cash_withholding=cash_withholding,
            )
        )
        if ambiguous:
            limitations.append(
                f"Realized dividend for {cash.symbol.strip()} had an ambiguous "
                "accrual match; accrual details were excluded."
            )
        elif accrual is None:
            limitations.append(
                f"Realized dividend for {cash.symbol.strip()} had no reliable "
                "accrual match; accrual details were excluded."
            )

    open_accruals = _reduce_accrual_lifecycle(dataset.open_dividend_accruals)
    expected: list[DividendIncomeLine] = []
    for accrual in open_accruals:
        if not start_date <= accrual.pay_date <= end_date:
            continue
        already_paid = any(
            _match_accrual(cash, [accrual])[0] is not None for cash in dividend_cash
        )
        if not already_paid:
            country = _country_for(
                conid=accrual.conid,
                symbol=accrual.symbol,
                currency=accrual.currency,
                instruments=dataset.instruments,
            )
            expected.append(
                _line_from_accrual(
                    accrual,
                    status="EXPECTED",
                    country=country,
                )
            )

    realized.sort(key=lambda row: (row.payment_date, row.symbol))
    expected.sort(key=lambda row: (row.payment_date, row.symbol))
    for line in realized + expected:
        native_values = (line.gross, line.withholding_tax, line.fee, line.net)
        if line.fx_rate_to_base is None and any(
            value is not None for value in native_values
        ):
            limitations.append(
                f"{line.status.title()} dividend for {line.symbol} has no Flex "
                "FX rate; native values were retained and base values excluded."
            )
    return DividendIncomeReport(
        start_date=start_date,
        end_date=end_date,
        base_currency=dataset.base_currency,
        realized_dividends=realized,
        expected_dividends=expected,
        summary=_summary(realized, expected),
        annual_estimate=_annual_estimate(
            dataset=dataset,
            accruals=accruals,
            end_date=end_date,
            history_start_date=effective_history_start,
            limitations=limitations,
        ),
        coverage_note=coverage_note,
        data_limitations=limitations,
    )
