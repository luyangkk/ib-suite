"""Pure mapping of raw option positions into a deterministic risk overview."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from ib_common.schema import (
    OptionExpirationBucket,
    OptionGreekCoverage,
    OptionPositionView,
    OptionUnderlyingConcentration,
    OptionsOverview,
    OptionsOverviewSummary,
)


_GREEKS = ("delta", "gamma", "theta", "vega")


def classify_moneyness(
    right: str, strike: float, underlying_price: float | None
) -> str | None:
    """Classify an option using the observed underlying price."""
    if right not in {"CALL", "PUT"}:
        raise ValueError(f"unsupported option right: {right!r}")
    if underlying_price is None:
        return None
    if underlying_price == strike:
        return "ATM"
    if right == "CALL":
        return "ITM" if underlying_price > strike else "OTM"
    return "ITM" if underlying_price < strike else "OTM"


def _scaled_greek(position: OptionPositionView, name: str) -> float | None:
    """Return the signed, contract-multiplier-adjusted Greek when available."""
    value = getattr(position, name)
    if value is None or position.fx_rate is None:
        return None
    return value * position.quantity * position.multiplier * position.fx_rate


def _contract_identifier(position: OptionPositionView) -> str:
    """Build the stable underlying, expiry, and strike identifier for coverage."""
    return (
        f"{position.underlying_symbol} {position.expiry_date.isoformat()} "
        f"{position.strike:g}"
    )


def _parse_multiplier(raw_multiplier: object, contract_id: str) -> int:
    """Parse a positive whole-number contract multiplier."""
    try:
        numeric = float(raw_multiplier)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{contract_id}: invalid multiplier {raw_multiplier!r}"
        ) from error
    if not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"{contract_id}: invalid multiplier {raw_multiplier!r}")
    return int(numeric)


def _parse_expiry(raw_expiry: object, contract_id: str) -> date:
    """Parse an ISO option expiry date with contract-specific diagnostics."""
    try:
        return date.fromisoformat(str(raw_expiry))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{contract_id}: invalid expiry_date {raw_expiry!r}") from error


def _limitations_for(position: OptionPositionView) -> list[str]:
    """Describe every unavailable data field needed for risk interpretation."""
    identifier = _contract_identifier(position)
    limitations: list[str] = []
    missing_greeks = [name for name in _GREEKS if getattr(position, name) is None]
    if missing_greeks:
        limitations.append(
            f"{identifier}: missing Greeks: {', '.join(missing_greeks)}"
        )
    if position.underlying_price is None:
        limitations.append(f"{identifier}: missing underlying price")
    if position.market_price is None:
        limitations.append(f"{identifier}: missing market price")
    if position.fx_rate is None:
        limitations.append(f"{identifier}: missing FX rate")
    return limitations


def _group_base_market_value(
    rows: list[OptionPositionView],
    group_name: str,
) -> tuple[float | None, float, str | None]:
    """Sum convertible exposure and disclose rows excluded for missing FX."""
    convertible = [
        abs(position.base_market_value)
        for position in rows
        if position.base_market_value is not None
    ]
    excluded = [
        _contract_identifier(position)
        for position in rows
        if position.base_market_value is None
    ]
    if not excluded:
        return sum(convertible), 1.0, None
    coverage_ratio = len(convertible) / len(rows)
    coverage = "partial" if convertible else "no"
    return (
        sum(convertible) if convertible else None,
        coverage_ratio,
        (
            f"{group_name}: {coverage} base market value coverage; "
            f"excluded {', '.join(excluded)}"
        ),
    )


def build_summary(
    options: list[OptionPositionView],
) -> tuple[OptionsOverviewSummary, list[str]]:
    """Aggregate Greeks and risk distributions from normalized option positions."""
    limitations: list[str] = []
    greek_coverage: dict[str, OptionGreekCoverage] = {}
    totals: dict[str, float | None] = {}

    for greek in _GREEKS:
        scaled_values: list[float] = []
        excluded: list[str] = []
        for position in options:
            scaled = _scaled_greek(position, greek)
            if scaled is None:
                excluded.append(_contract_identifier(position))
            else:
                scaled_values.append(scaled)
        greek_coverage[greek] = OptionGreekCoverage(
            contributing_contracts=len(scaled_values),
            excluded_contracts=excluded,
        )
        totals[greek] = round(sum(scaled_values), 12) if scaled_values else None

    expiry_rows: dict[date, list[OptionPositionView]] = defaultdict(list)
    underlying_rows: dict[str, list[OptionPositionView]] = defaultdict(list)
    for position in options:
        expiry_rows[position.expiry_date].append(position)
        underlying_rows[position.underlying_symbol].append(position)

    expiration_distribution: list[OptionExpirationBucket] = []
    for expiry, rows in sorted(expiry_rows.items()):
        absolute_value, coverage, limitation = _group_base_market_value(
            rows, f"expiration {expiry.isoformat()}"
        )
        expiration_distribution.append(
            OptionExpirationBucket(
                expiry_date=expiry,
                contract_count=len(rows),
                quantity=sum(position.quantity for position in rows),
                absolute_base_market_value=absolute_value,
                base_market_value_coverage=coverage,
            )
        )
        if limitation:
            limitations.append(limitation)

    absolute_values: dict[str, tuple[float | None, float]] = {}
    for symbol, rows in underlying_rows.items():
        absolute_value, coverage, limitation = _group_base_market_value(
            rows, f"underlying {symbol}"
        )
        absolute_values[symbol] = (absolute_value, coverage)
        if limitation:
            limitations.append(limitation)

    concentration_denom = sum(
        value
        for value, _ in absolute_values.values()
        if value is not None
    )
    underlying_concentration = sorted(
        [
            OptionUnderlyingConcentration(
                underlying_symbol=symbol,
                absolute_base_market_value=value,
                base_market_value_coverage=coverage,
                weight=(
                    value / concentration_denom
                    if value is not None and concentration_denom
                    else None
                ),
            )
            for symbol, (value, coverage) in absolute_values.items()
        ],
        key=lambda row: (
            row.absolute_base_market_value is None,
            -(row.absolute_base_market_value or 0.0),
            row.underlying_symbol,
        ),
    )

    return (
        OptionsOverviewSummary(
            total_delta=totals["delta"],
            total_gamma=totals["gamma"],
            total_theta=totals["theta"],
            total_vega=totals["vega"],
            daily_time_value_decay=(
                -totals["theta"] if totals["theta"] is not None else None
            ),
            greek_coverage=greek_coverage,
            expiration_distribution=expiration_distribution,
            underlying_concentration=underlying_concentration,
        ),
        limitations,
    )


def build_options_overview(
    raw: dict, report_date: date, ts: datetime
) -> OptionsOverview:
    """Map raw account option data into typed positions and aggregate risk."""
    account = raw["account"]
    account_id = account["account_id"]
    views: list[OptionPositionView] = []
    limitations: list[str] = []

    for option in raw["options"]:
        contract_id = str(option.get("contract_id", "<unknown contract>"))
        expiry_date = _parse_expiry(option.get("expiry_date"), contract_id)
        multiplier = _parse_multiplier(option.get("multiplier"), contract_id)
        right = option["right"]
        try:
            moneyness = classify_moneyness(
                right, float(option["strike"]), option.get("underlying_price")
            )
        except ValueError as error:
            raise ValueError(f"{contract_id}: right: {error}") from error

        fx_rate = option.get("fx_rate")
        view = OptionPositionView(
            account_id=account_id,
            underlying_symbol=option["underlying_symbol"],
            right=right,
            quantity=float(option["quantity"]),
            strike=float(option["strike"]),
            expiry_date=expiry_date,
            days_to_expiry=(expiry_date - report_date).days + 1,
            avg_cost=float(option["avg_cost"]),
            market_price=(
                float(option["market_price"])
                if option.get("market_price") is not None
                else None
            ),
            market_value=float(option["market_value"]),
            unrealized_pnl=float(option["unrealized_pnl"]),
            currency=option["currency"],
            multiplier=multiplier,
            implied_volatility=option.get("implied_volatility"),
            delta=option.get("delta"),
            gamma=option.get("gamma"),
            theta=option.get("theta"),
            vega=option.get("vega"),
            underlying_price=option.get("underlying_price"),
            moneyness=moneyness,
            greeks_status=(
                "COMPLETE"
                if all(option.get(greek) is not None for greek in _GREEKS)
                else "INCOMPLETE"
            ),
            fx_rate=fx_rate,
            base_market_value=(
                float(option["market_value"]) * fx_rate
                if fx_rate is not None
                else None
            ),
            base_unrealized_pnl=(
                float(option["unrealized_pnl"]) * fx_rate
                if fx_rate is not None
                else None
            ),
        )
        views.append(view)
        limitations.extend(_limitations_for(view))

    summary, summary_limitations = build_summary(views)
    return OptionsOverview(
        account_id=account_id,
        base_currency=account["base_currency"],
        options=views,
        summary=summary,
        data_limitations=limitations + summary_limitations,
        ts=ts,
    )
