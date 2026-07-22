"""Tests for deterministic dividend reconciliation, aggregation, and estimates."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from ib_common.dividend_income import build_dividend_income_report, listing_country
from ib_common.schema import (
    FlexCashTransaction,
    FlexDividendAccrual,
    FlexDividendDataset,
    FlexInstrument,
    FlexOpenPosition,
)


def _cash(
    *,
    symbol: str = "AAPL",
    conid: str | None = "1",
    payment_date: date = date(2026, 7, 15),
    amount: float = 25.0,
    transaction_type: str = "Dividends",
    currency: str = "USD",
    fx_rate_to_base: float | None = 1.0,
    code: str = "PO",
    trade_id: str | None = None,
) -> FlexCashTransaction:
    """Build a cash transaction with stable defaults for focused tests."""
    return FlexCashTransaction(
        account_id="U1",
        currency=currency,
        asset_class="STK",
        fx_rate_to_base=fx_rate_to_base,
        symbol=symbol,
        description=None,
        conid=conid,
        underlying_conid=None,
        underlying_symbol=None,
        ts=datetime.combine(payment_date, datetime.min.time(), tzinfo=timezone.utc),
        amount=amount,
        transaction_type=transaction_type,
        trade_id=trade_id,
        code=code,
    )


def _accrual(
    *,
    symbol: str = "AAPL",
    conid: str | None = "1",
    ex_date: date = date(2026, 7, 8),
    pay_date: date = date(2026, 7, 15),
    gross: float | None = 25.0,
    tax: float | None = -3.75,
    fee: float | None = 0.0,
    net: float | None = 21.25,
    quantity: float | None = 100.0,
    gross_rate: float | None = 0.25,
    currency: str = "USD",
    code: str = "PO",
    fx_rate_to_base: float | None = 1.0,
) -> FlexDividendAccrual:
    """Build a dividend accrual with stable defaults for focused tests."""
    return FlexDividendAccrual(
        account_id="U1",
        currency=currency,
        asset_class="STK",
        fx_rate_to_base=fx_rate_to_base,
        symbol=symbol,
        description=None,
        conid=conid,
        accrual_date=ex_date,
        ex_date=ex_date,
        pay_date=pay_date,
        quantity=quantity,
        tax=tax,
        fee=fee,
        gross_rate=gross_rate,
        gross_amount=gross,
        net_amount=net,
        code=code,
        report_date=ex_date,
    )


def _dataset(
    *,
    cash: list[FlexCashTransaction] | None = None,
    accruals: list[FlexDividendAccrual] | None = None,
    open_accruals: list[FlexDividendAccrual] | None = None,
    positions: list[FlexOpenPosition] | None = None,
    instruments: list[FlexInstrument] | None = None,
) -> FlexDividendDataset:
    """Build a minimal typed dividend dataset for calculation tests."""
    return FlexDividendDataset(
        base_currency="USD",
        cash_transactions=cash or [],
        dividend_accruals=accruals or [],
        open_dividend_accruals=open_accruals or [],
        open_positions=positions or [],
        instruments=instruments or [],
    )


def _instrument(
    *,
    symbol: str = "AAPL",
    conid: str | None = "1",
    currency: str = "USD",
    exchange: str | None = "NASDAQ",
    isin: str | None = "US0378331005",
) -> FlexInstrument:
    """Build listing metadata with stable defaults for country attribution."""
    return FlexInstrument(
        asset_class="STK",
        symbol=symbol,
        currency=currency,
        listing_exchange=exchange,
        description=None,
        conid=conid,
        isin=isin,
        multiplier=1.0,
        security_subtype="COMMON",
    )


def _position(
    *,
    symbol: str = "AAPL",
    conid: str | None = "1",
    asset_class: str = "STK",
    currency: str = "USD",
    quantity: float | None = 100.0,
    position_value: float | None = 10_000.0,
    fx_rate_to_base: float | None = 1.0,
    side: str = "LONG",
    level_of_detail: str = "SUMMARY",
    report_date: date = date(2026, 7, 31),
    account_id: str = "U1",
) -> FlexOpenPosition:
    """Build a current Flex position with stable annual-estimate defaults."""
    return FlexOpenPosition(
        account_id=account_id,
        currency=currency,
        asset_class=asset_class,
        fx_rate_to_base=fx_rate_to_base,
        symbol=symbol,
        conid=conid,
        report_date=report_date,
        quantity=quantity,
        multiplier=1.0,
        mark_price=None,
        position_value=position_value,
        side=side,
        level_of_detail=level_of_detail,
    )


def _two_dividends_one_withholding_dataset(
    *, include_position: bool = False
) -> FlexDividendDataset:
    """Build two realized events competing for one withholding cash posting."""
    return _dataset(
        cash=[
            _cash(payment_date=date(2026, 7, 15), trade_id="DIVIDEND1"),
            _cash(payment_date=date(2026, 7, 16), trade_id="DIVIDEND2"),
            _cash(
                amount=-3.75,
                transaction_type="Withholding Tax",
                payment_date=date(2026, 7, 15),
                trade_id="TAX1",
            ),
        ],
        accruals=[
            _accrual(
                ex_date=date(2026, 7, 8),
                pay_date=date(2026, 7, 15),
                tax=None,
                net=None,
            ),
            _accrual(
                ex_date=date(2026, 7, 9),
                pay_date=date(2026, 7, 16),
                tax=None,
                net=None,
            ),
        ],
        positions=[_position()] if include_position else [],
    )


def test_reconcile_realized_and_expected_dividends() -> None:
    """A posted dividend is realized while a different open accrual is expected."""
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(amount=-3.75, transaction_type="Withholding Tax"),
        ],
        accruals=[_accrual()],
        open_accruals=[
            _accrual(
                symbol="NEXT",
                conid="2",
                ex_date=date(2026, 8, 1),
                pay_date=date(2026, 8, 15),
                gross=10.0,
                tax=-1.0,
                net=9.0,
            )
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 8, 31)
    )

    assert [row.status for row in report.realized_dividends] == ["REALIZED"]
    realized = report.realized_dividends[0]
    assert realized.gross == 25.0
    assert realized.withholding_tax == 3.75
    assert realized.net == 21.25
    assert realized.quantity == 100
    assert [row.status for row in report.expected_dividends] == ["EXPECTED"]


def test_reconcile_unique_cash_withholding_fills_missing_accrual_tax() -> None:
    """One associated withholding posting supplies tax when the accrual omits it."""
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(amount=-3.75, transaction_type="Withholding Tax"),
        ],
        accruals=[_accrual(tax=None)],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends[0].withholding_tax == 3.75
    assert report.realized_dividends[0].base_withholding_tax == 3.75


def test_reconcile_exact_conid_outranks_symbol_candidate() -> None:
    """An exact conid association wins over another accrual sharing the symbol."""
    dataset = _dataset(
        cash=[_cash(conid="2")],
        accruals=[
            _accrual(conid="1", gross=10.0, net=10.0),
            _accrual(conid="2", gross=25.0, net=25.0),
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends[0].gross == 25.0


def test_reconcile_prefers_exact_pay_date_then_unique_three_day_tolerance() -> None:
    """Exact pay dates outrank unique candidates within three calendar days."""
    dataset = _dataset(
        cash=[
            _cash(symbol="EXACT", conid="1"),
            _cash(symbol="NEAR", conid="2"),
            _cash(symbol="FAR", conid="3"),
        ],
        accruals=[
            _accrual(symbol="EXACT", conid="1", gross=25.0),
            _accrual(
                symbol="EXACT",
                conid="1",
                pay_date=date(2026, 7, 16),
                gross=10.0,
            ),
            _accrual(
                symbol="NEAR",
                conid="2",
                pay_date=date(2026, 7, 18),
                gross=30.0,
            ),
            _accrual(
                symbol="FAR",
                conid="3",
                pay_date=date(2026, 7, 19),
                gross=40.0,
            ),
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert {row.symbol: row.gross for row in report.realized_dividends} == {
        "EXACT": 25.0,
        "NEAR": 30.0,
        # The FAR accrual is beyond the pay-date tolerance, so no accrual is
        # matched; the confirmed cash amount is still credited as gross.
        "FAR": 25.0,
    }


def test_reconcile_uses_unique_normalized_symbol_fallback() -> None:
    """A missing conid can fall back to one normalized symbol candidate."""
    dataset = _dataset(
        cash=[_cash(symbol=" brk.b ", conid=None)],
        accruals=[_accrual(symbol="BRK B", conid="2")],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends[0].gross == 25.0
    assert report.realized_dividends[0].quantity == 100.0


def test_reconcile_leaves_ambiguous_symbol_fallback_unmatched() -> None:
    """Multiple equally ranked symbol candidates never receive an arbitrary match."""
    dataset = _dataset(
        cash=[_cash(conid=None)],
        accruals=[
            _accrual(conid="1", ex_date=date(2026, 7, 7)),
            _accrual(conid="2", ex_date=date(2026, 7, 8)),
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    realized = report.realized_dividends[0]
    assert realized.gross is None
    assert realized.withholding_tax is None
    assert realized.net == 25.0
    assert realized.quantity is None
    assert any("ambiguous" in item.lower() for item in report.data_limitations)


def test_reconcile_unmatched_gross_cash_subtracts_unique_withholding_from_net() -> None:
    """Confirmed gross cash and unique tax preserve a reliable unmatched net amount."""
    dataset = _dataset(
        cash=[
            _cash(amount=25.0),
            _cash(amount=-3.75, transaction_type="Withholding Tax"),
        ]
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    realized = report.realized_dividends[0]
    assert realized.gross == 25.0
    assert realized.withholding_tax == 3.75
    assert realized.net == 21.25
    assert realized.base_net == 21.25


def test_unmatched_dividend_cash_falls_back_to_cash_amount_for_gross() -> None:
    """Confirmed dividend cash without any accrual still reports gross from cash."""
    dataset = _dataset(cash=[_cash(amount=1.40)])

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    realized = report.realized_dividends[0]
    assert realized.gross == 1.40
    assert realized.base_gross == 1.40
    assert realized.net == 1.40


def test_split_dividend_and_payment_in_lieu_each_report_own_gross() -> None:
    """A dividend split into two cash rows against a zeroed accrual reports both."""
    posting = _accrual(gross=312.98, net=281.68, tax=-31.30)
    payout_reversal = posting.model_copy(
        update={
            "accrual_date": posting.pay_date,
            "quantity": -100.0,
            "tax": 31.30,
            "gross_rate": 0.6359,
            "gross_amount": -312.98,
            "net_amount": -281.68,
            "code": "RE",
            "report_date": posting.pay_date,
        }
    )
    dataset = _dataset(
        cash=[
            _cash(amount=195.03, transaction_type="Dividends"),
            _cash(amount=117.94, transaction_type="Payment In Lieu Of Dividends"),
        ],
        accruals=[posting, payout_reversal],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    grosses = sorted(line.gross for line in report.realized_dividends)
    assert grosses == [117.94, 195.03]
    assert report.summary.realized.gross == pytest.approx(312.97)


def test_reconcile_unmatched_cash_keeps_net_null_for_ambiguous_withholding() -> None:
    """Ambiguous separate tax postings cannot fabricate an unmatched cash net."""
    dataset = _dataset(
        cash=[
            _cash(amount=25.0, conid=None),
            _cash(
                amount=-2.0,
                transaction_type="Withholding Tax",
                conid="TAX1",
            ),
            _cash(
                amount=-1.75,
                transaction_type="Withholding Tax",
                conid="TAX2",
            ),
        ]
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends[0].net is None
    assert any(
        "withholding" in limitation.lower() and "ambiguous" in limitation.lower()
        for limitation in report.data_limitations
    )


def test_reconcile_reduces_post_reversal_and_corrected_posting_lifecycle() -> None:
    """A reversed posting and its corrected replacement form one realized event."""
    dataset = _dataset(
        cash=[_cash(amount=30.0)],
        accruals=[
            _accrual(),
            _accrual(
                gross=-25.0,
                tax=3.75,
                net=-21.25,
                quantity=-100.0,
                gross_rate=-0.25,
                code="RE",
            ),
            _accrual(
                gross=30.0,
                tax=-4.5,
                net=25.5,
                quantity=100.0,
                gross_rate=0.3,
            ),
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    realized = report.realized_dividends[0]
    assert realized.gross == 30.0
    assert realized.withholding_tax == 4.5
    assert realized.net == 25.5
    assert realized.quantity == 100.0


def test_reconcile_cash_confirmed_po_re_payout_retains_economic_accrual() -> None:
    """A pay-date Re closes an accrual but confirmed cash preserves its economics."""
    posting = _accrual()
    payout_reversal = posting.model_copy(
        update={
            "accrual_date": posting.pay_date,
            "quantity": -100.0,
            "tax": 3.75,
            "fee": 0.0,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
            "report_date": posting.pay_date,
        }
    )
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(amount=-3.75, transaction_type="Withholding Tax"),
        ],
        accruals=[posting, payout_reversal],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    realized = report.realized_dividends[0]
    assert realized.gross == 25.0
    assert realized.quantity == 100.0
    assert report.summary.realized.gross == 25.0
    assert report.annual_estimate.holdings[0].trailing_gross_rate == 0.25
    assert report.annual_estimate.estimated_base_gross == 25.0


def test_reconcile_cash_confirmed_po_re_with_unsigned_rate_retains_gross() -> None:
    """Real IBKR reversals keep a positive gross_rate; cash must still confirm gross."""
    posting = _accrual()
    # IBKR emits the reversal with a NEGATED amount but an UNCHANGED per-share rate.
    payout_reversal = posting.model_copy(
        update={
            "accrual_date": posting.pay_date,
            "quantity": -100.0,
            "tax": 3.75,
            "fee": 0.0,
            "gross_rate": 0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
            "report_date": posting.pay_date,
        }
    )
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(amount=-3.75, transaction_type="Withholding Tax"),
        ],
        accruals=[posting, payout_reversal],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    realized = report.realized_dividends[0]
    assert realized.gross == 25.0
    assert report.summary.realized.gross == 25.0


def test_reconcile_cash_confirmed_po_re_with_subcent_residue_retains_gross() -> None:
    """A one-cent rounding residue in a cancelled pair must not fake a live event."""
    posting = _accrual(net=224.69, gross=249.65, tax=-24.96, gross_rate=0.6089)
    payout_reversal = posting.model_copy(
        update={
            "accrual_date": posting.pay_date,
            "quantity": -100.0,
            "tax": 24.96,
            "fee": 0.0,
            "gross_rate": 0.6089,
            "gross_amount": -249.65,
            # IBKR leaves a sub-cent residue on the reversal net.
            "net_amount": -224.68,
            "code": "RE",
            "report_date": posting.pay_date,
        }
    )
    dataset = _dataset(
        cash=[
            _cash(amount=249.65),
            _cash(amount=-24.96, transaction_type="Withholding Tax"),
        ],
        accruals=[posting, payout_reversal],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    realized = report.realized_dividends[0]
    assert realized.gross == 249.65
    assert report.summary.realized.gross == 249.65


def test_reconcile_po_re_without_confirmed_cash_remains_cancelled() -> None:
    """The same zeroed lifecycle without surviving cash is a genuine cancellation."""
    posting = _accrual()
    reversal = posting.model_copy(
        update={
            "quantity": -100.0,
            "tax": 3.75,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
        }
    )
    report = build_dividend_income_report(
        _dataset(accruals=[posting, reversal], positions=[_position()]),
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    assert report.realized_dividends == []
    assert report.annual_estimate.estimated_base_gross == 0.0


def test_mixed_conid_po_re_without_cash_cancels_annual_accrual() -> None:
    """A conidless reversal cancels its unique conid posting by secondary key."""
    posting = _accrual(conid="1")
    reversal = posting.model_copy(
        update={
            "conid": None,
            "quantity": -100.0,
            "tax": 3.75,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
        }
    )

    report = build_dividend_income_report(
        _dataset(accruals=[posting, reversal], positions=[_position(conid="1")]),
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    assert report.realized_dividends == []
    assert report.annual_estimate.holdings[0].trailing_gross_rate == 0.0
    assert report.annual_estimate.estimated_base_gross == 0.0


def test_mixed_conid_po_re_with_cash_preserves_confirmed_payout() -> None:
    """Cash still proves a payout after its conidless reversal is coalesced."""
    posting = _accrual(conid="1")
    payout_reversal = posting.model_copy(
        update={
            "conid": None,
            "accrual_date": posting.pay_date,
            "quantity": -100.0,
            "tax": 3.75,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
            "report_date": posting.pay_date,
        }
    )

    report = build_dividend_income_report(
        _dataset(
            cash=[_cash(conid="1", amount=25.0)],
            accruals=[posting, payout_reversal],
            positions=[_position(conid="1")],
        ),
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    assert report.realized_dividends[0].gross == 25.0
    assert report.realized_dividends[0].quantity == 100.0
    assert report.annual_estimate.holdings[0].trailing_gross_rate == 0.25


def test_conidless_reversal_stays_ambiguous_across_multiple_conids() -> None:
    """A secondary-key fallback never chooses between two possible conid events."""
    first_posting = _accrual(conid="1")
    second_posting = _accrual(conid="2")
    reversal = first_posting.model_copy(
        update={
            "conid": None,
            "quantity": -100.0,
            "tax": 3.75,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
        }
    )

    report = build_dividend_income_report(
        _dataset(
            accruals=[first_posting, second_posting, reversal],
            positions=[_position(conid="1"), _position(conid="2")],
        ),
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    assert [
        holding.trailing_gross_rate
        for holding in report.annual_estimate.holdings
    ] == [0.25, 0.25]
    assert report.annual_estimate.estimated_base_gross == 50.0


def test_zeroed_lifecycle_cash_amount_disagreement_keeps_cash_only_facts() -> None:
    """Known unequal accrual and cash gross amounts cannot revive stale economics."""
    posting = _accrual(gross=25.0)
    payout_reversal = posting.model_copy(
        update={
            "accrual_date": posting.pay_date,
            "quantity": -100.0,
            "tax": 3.75,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
            "report_date": posting.pay_date,
        }
    )

    report = build_dividend_income_report(
        _dataset(
            cash=[_cash(amount=30.0)],
            accruals=[posting, payout_reversal],
            positions=[_position()],
        ),
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    realized = report.realized_dividends[0]
    # The accrual gross disagreed with the confirmed cash, so accrual-derived
    # details (quantity, withholding, fee) are dropped; gross falls back to the
    # cash that actually posted.
    assert realized.gross == 30.0
    assert realized.quantity is None
    assert realized.withholding_tax is None
    assert realized.fee is None
    assert realized.net == 30.0
    assert report.summary.realized.gross == 30.0
    assert report.annual_estimate.holdings[0].trailing_gross_rate == 0.0
    assert report.annual_estimate.estimated_base_gross == 0.0
    assert any(
        "gross-amount discrepancy" in limitation.lower()
        and "cash-only" in limitation.lower()
        for limitation in report.data_limitations
    )
    assert any(
        "no reliable accrual match" in limitation.lower()
        for limitation in report.data_limitations
    )


def test_reconcile_cash_confirmed_po_re_uses_missing_conid_symbol_fallback() -> None:
    """Cash can prove a zeroed payout when only the accrual omits its conid."""
    posting = _accrual(conid=None)
    reversal = posting.model_copy(
        update={
            "quantity": -100.0,
            "tax": 3.75,
            "gross_rate": -0.25,
            "gross_amount": -25.0,
            "net_amount": -21.25,
            "code": "RE",
        }
    )

    report = build_dividend_income_report(
        _dataset(cash=[_cash(conid="1")], accruals=[posting, reversal]),
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    assert report.realized_dividends[0].gross == 25.0
    assert report.realized_dividends[0].quantity == 100.0


def test_reconcile_reduces_reversed_cash_posting_before_realization() -> None:
    """A fully reversed cash dividend is not treated as confirmed realized income."""
    dataset = _dataset(
        cash=[
            _cash(amount=25.0, code="PO"),
            _cash(amount=-25.0, code="RE"),
        ],
        accruals=[_accrual()],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends == []


def test_reconcile_cash_reversal_ignores_changed_trade_ids() -> None:
    """Cash lifecycle identity does not split one event when a reversal ID changes."""
    dataset = _dataset(
        cash=[
            _cash(amount=25.0, code="PO", trade_id="ORIGINAL"),
            _cash(amount=-25.0, code="RE", trade_id="REVERSAL"),
        ],
        accruals=[_accrual()],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends == []


def test_reconcile_delayed_positive_reversal_cancels_original_cash_posting() -> None:
    """A later-date RE row cancels its earlier posting by stable cash identity."""
    dataset = _dataset(
        cash=[
            _cash(amount=25.0, payment_date=date(2026, 7, 15), code="PO"),
            _cash(amount=25.0, payment_date=date(2026, 7, 16), code="RE"),
        ],
        accruals=[_accrual()],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends == []


def test_reconcile_recurring_reversal_prefers_older_matching_trade_id() -> None:
    """A targeted reversal cancels its older trade, not a newer equal dividend."""
    dataset = _dataset(
        cash=[
            _cash(
                payment_date=date(2026, 6, 15),
                trade_id="OLDER",
            ),
            _cash(
                payment_date=date(2026, 7, 15),
                trade_id="NEWER",
            ),
            _cash(
                payment_date=date(2026, 7, 20),
                trade_id="OLDER",
                code="RE",
            ),
        ],
        accruals=[_accrual(pay_date=date(2026, 7, 15))],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert [row.payment_date for row in report.realized_dividends] == [
        date(2026, 7, 15)
    ]
    assert report.realized_dividends[0].gross == 25.0


def test_reconcile_ambiguous_no_id_reversal_preserves_recurring_dividends() -> None:
    """A no-ID reversal preserves equal candidates and discloses its ambiguity."""
    dataset = _dataset(
        cash=[
            _cash(payment_date=date(2026, 6, 15)),
            _cash(payment_date=date(2026, 7, 15)),
            _cash(payment_date=date(2026, 7, 20), code="RE"),
        ],
        accruals=[_accrual(pay_date=date(2026, 7, 15))],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert [row.payment_date for row in report.realized_dividends] == [
        date(2026, 7, 15)
    ]
    assert any(
        "cash reversal" in limitation.lower()
        and "ambiguous" in limitation.lower()
        for limitation in report.data_limitations
    )


def test_reconcile_withholding_reversal_removes_tax_deduction() -> None:
    """A fully reversed withholding lifecycle contributes no line or summary tax."""
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(
                amount=-3.75,
                transaction_type="Withholding Tax",
                payment_date=date(2026, 7, 15),
                code="PO",
            ),
            _cash(
                amount=3.75,
                transaction_type="Withholding Tax",
                payment_date=date(2026, 7, 16),
                code="RE",
            ),
        ],
        accruals=[_accrual(tax=None, net=None)],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.realized_dividends[0].withholding_tax is None
    assert report.summary.realized.withholding_tax is None


def test_reconcile_consumes_one_withholding_across_nearby_dividends_once() -> None:
    """One tax posting belongs to only its best dividend cash match."""
    report = build_dividend_income_report(
        _two_dividends_one_withholding_dataset(),
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    assert [row.withholding_tax for row in report.realized_dividends] == [
        3.75,
        None,
    ]
    assert any(
        "withholding" in limitation.lower()
        and "ambiguous" in limitation.lower()
        for limitation in report.data_limitations
    )


def test_reconcile_consumes_exact_accrual_before_tolerant_cash_match() -> None:
    """One accrual supplies details once, with an exact cash match outranking near."""
    dataset = _dataset(
        cash=[
            _cash(payment_date=date(2026, 7, 15), trade_id="EXACT"),
            _cash(payment_date=date(2026, 7, 16), trade_id="NEAR"),
        ],
        accruals=[_accrual(pay_date=date(2026, 7, 15))],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert [row.gross for row in report.realized_dividends] == [25.0, None]
    assert report.summary.realized.gross == 25.0


def test_reconcile_equal_tier_many_to_one_cash_matches_stay_unmatched() -> None:
    """Two tolerant cash candidates cannot arbitrarily consume one accrual event."""
    dataset = _dataset(
        cash=[
            _cash(payment_date=date(2026, 7, 14), trade_id="EARLY"),
            _cash(payment_date=date(2026, 7, 16), trade_id="LATE"),
        ],
        accruals=[_accrual(pay_date=date(2026, 7, 15))],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert [row.gross for row in report.realized_dividends] == [None, None]
    assert report.summary.realized.gross is None


def test_expected_excludes_an_open_accrual_already_paid() -> None:
    """A paid economic event is not also reported from open accruals as expected."""
    accrual = _accrual()
    dataset = _dataset(
        cash=[_cash()],
        accruals=[accrual],
        open_accruals=[accrual.model_copy(update={"accrual_date": None})],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert len(report.realized_dividends) == 1
    assert report.expected_dividends == []


def test_expected_keeps_ambiguous_open_events_when_cash_match_is_not_unique() -> None:
    """One cash row cannot suppress multiple equally ranked open dividend events."""
    dataset = _dataset(
        cash=[_cash()],
        open_accruals=[
            _accrual(ex_date=date(2026, 7, 7)),
            _accrual(ex_date=date(2026, 7, 8)),
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert len(report.expected_dividends) == 2


def test_inclusive_payment_boundaries_filter_realized_and_expected_rows() -> None:
    """Realized and expected payment dates include both requested boundaries."""
    start = date(2026, 7, 1)
    end = date(2026, 7, 31)
    dataset = _dataset(
        cash=[
            _cash(symbol="START", conid="1", payment_date=start),
            _cash(symbol="END", conid="2", payment_date=end),
            _cash(symbol="LATE", conid="3", payment_date=date(2026, 8, 1)),
        ],
        accruals=[
            _accrual(symbol="START", conid="1", pay_date=start),
            _accrual(symbol="END", conid="2", pay_date=end),
            _accrual(symbol="LATE", conid="3", pay_date=date(2026, 8, 1)),
        ],
        open_accruals=[
            _accrual(symbol="OPEN_START", conid="4", pay_date=start),
            _accrual(symbol="OPEN_END", conid="5", pay_date=end),
            _accrual(
                symbol="OPEN_EARLY",
                conid="6",
                pay_date=date(2026, 6, 30),
            ),
        ],
    )

    report = build_dividend_income_report(dataset, start, end)

    assert [row.symbol for row in report.realized_dividends] == ["START", "END"]
    assert [row.symbol for row in report.expected_dividends] == [
        "OPEN_START",
        "OPEN_END",
    ]


def test_aggregate_separates_status_and_attributes_native_and_base_totals() -> None:
    """Summary totals preserve status, native currencies, and base countries."""
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(
                symbol="SGFUND",
                conid="2",
                amount=20.0,
                currency="SGD",
                fx_rate_to_base=0.75,
            ),
        ],
        accruals=[
            _accrual(),
            _accrual(
                symbol="SGFUND",
                conid="2",
                gross=20.0,
                tax=-2.0,
                fee=-0.5,
                net=17.5,
                currency="SGD",
                fx_rate_to_base=0.75,
            ),
        ],
        open_accruals=[
            _accrual(
                symbol="NEXT",
                conid="3",
                pay_date=date(2026, 7, 20),
                gross=10.0,
                tax=-1.0,
                net=9.0,
                currency="EUR",
                fx_rate_to_base=1.1,
            )
        ],
        instruments=[
            _instrument(),
            _instrument(
                symbol="SGFUND",
                conid="2",
                currency="SGD",
                exchange="SGX",
                isin="SG0000000001",
            ),
            _instrument(
                symbol="NEXT",
                conid="3",
                currency="EUR",
                exchange=None,
                isin="DE0000000001",
            ),
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    assert report.summary.realized.model_dump() == {
        "gross": pytest.approx(40.0),
        "withholding_tax": pytest.approx(5.25),
        "fee": pytest.approx(0.375),
        "net": pytest.approx(34.375),
    }
    assert report.summary.expected.model_dump() == {
        "gross": pytest.approx(11.0),
        "withholding_tax": pytest.approx(1.1),
        "fee": pytest.approx(0.0),
        "net": pytest.approx(9.9),
    }
    assert report.summary.by_currency.realized["USD"].gross == 25.0
    assert report.summary.by_currency.realized["SGD"].gross == 20.0
    assert "EUR" not in report.summary.by_currency.realized
    assert report.summary.by_currency.expected["EUR"].gross == 10.0
    assert "USD" not in report.summary.by_currency.expected
    assert report.summary.by_country.realized["US"].gross == 25.0
    assert report.summary.by_country.realized["SG"].gross == 15.0
    assert "DE" not in report.summary.by_country.realized
    assert report.summary.by_country.expected["DE"].gross == pytest.approx(11.0)
    assert [item.symbol for item in report.summary.top_contributors] == [
        "AAPL",
        "SGFUND",
    ]
    assert [item.base_net for item in report.summary.top_contributors] == [
        pytest.approx(21.25),
        pytest.approx(13.125),
    ]
    sg_line = next(
        row for row in report.realized_dividends if row.symbol == "SGFUND"
    )
    assert sg_line.withholding_tax == 2.0
    assert sg_line.fee == 0.5
    assert sg_line.base_withholding_tax == 1.5
    assert sg_line.base_fee == 0.375


def test_aggregate_missing_fx_keeps_native_values_and_null_base_values() -> None:
    """A missing Flex FX rate excludes base totals without losing native facts."""
    dataset = _dataset(
        cash=[_cash(currency="CAD", fx_rate_to_base=None)],
        accruals=[_accrual(currency="CAD", fx_rate_to_base=None)],
        instruments=[
            _instrument(currency="CAD", exchange="TSX", isin="CA0000000001")
        ],
    )

    report = build_dividend_income_report(
        dataset, date(2026, 7, 1), date(2026, 7, 31)
    )

    line = report.realized_dividends[0]
    assert line.gross == 25.0
    assert line.net == 21.25
    assert line.base_gross is None
    assert line.base_withholding_tax is None
    assert line.base_fee is None
    assert line.base_net is None
    assert report.summary.realized.model_dump() == {
        "gross": None,
        "withholding_tax": None,
        "fee": None,
        "net": None,
    }
    assert report.summary.by_currency.realized["CAD"].gross == 25.0
    assert report.summary.by_currency.expected == {}
    assert report.summary.by_country.realized == {}
    assert report.summary.by_country.expected == {}
    assert any("fx" in item.lower() for item in report.data_limitations)


def test_country_attribution_accepts_duplicate_agreeing_instrument_rows() -> None:
    """Duplicate SecurityInfo facts with the same country are not ambiguous."""
    instrument = _instrument()
    report = build_dividend_income_report(
        _dataset(
            cash=[_cash()],
            accruals=[_accrual()],
            instruments=[instrument, instrument.model_copy()],
        ),
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    assert report.realized_dividends[0].country == "US"
    assert report.summary.by_country.realized["US"].gross == 25.0


def test_country_attribution_keeps_genuinely_conflicting_instruments_unknown() -> None:
    """Two conid matches with different listing countries remain unresolved."""
    report = build_dividend_income_report(
        _dataset(
            cash=[_cash()],
            accruals=[_accrual()],
            instruments=[
                _instrument(exchange="NASDAQ", isin="US0378331005"),
                _instrument(exchange="SGX", isin="SG0000000001"),
            ],
        ),
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    assert report.realized_dividends[0].country == "UNKNOWN"


def test_unique_cash_withholding_overrides_stale_accrual_tax_and_annual_rate() -> None:
    """Actual posted tax drives realized and annual results when accrual disagrees."""
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(amount=-5.0, transaction_type="Withholding Tax"),
        ],
        accruals=[_accrual(tax=-3.75, net=21.25)],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    realized = report.realized_dividends[0]
    assert realized.withholding_tax == 5.0
    assert realized.net == 20.0
    assert realized.base_withholding_tax == 5.0
    assert realized.base_net == 20.0
    holding = report.annual_estimate.holdings[0]
    assert holding.effective_tax_rate == pytest.approx(0.2)
    assert holding.estimated_net == pytest.approx(20.0)
    assert any(
        "posted withholding" in limitation.lower()
        and "accrual tax" in limitation.lower()
        for limitation in report.data_limitations
    )


def test_agreeing_cash_withholding_preserves_known_net_when_fee_is_missing() -> None:
    """An agreeing tax posting must not erase an already reported accrual net."""
    dataset = _dataset(
        cash=[
            _cash(),
            _cash(amount=-3.75, transaction_type="Withholding Tax"),
        ],
        accruals=[_accrual(tax=-3.75, fee=None, net=21.25)],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    realized = report.realized_dividends[0]
    assert realized.withholding_tax == 3.75
    assert realized.net == 21.25
    assert realized.base_net == 21.25


@pytest.mark.parametrize(
    ("exchange", "isin", "expected"),
    [
        ("NASDAQ", "", "US"),
        ("sgx", "", "SG"),
        ("", "JP0000000001", "JP"),
        ("", "XS0000000001", "UNKNOWN"),
        ("", "ZZ0000000001", "UNKNOWN"),
        ("MYSTERY", "US0000000001", "UNKNOWN"),
        ("", "", "UNKNOWN"),
    ],
)
def test_listing_country_uses_exchange_then_absent_exchange_isin_fallback(
    exchange: str, isin: str, expected: str
) -> None:
    """Listing exchange wins and ISIN prefixes apply only when it is absent."""
    assert listing_country(exchange, isin) == expected


def test_annual_estimate_uses_current_eligible_holdings_and_trailing_rates() -> None:
    """Annual gross and yield use trailing rates and every eligible long holding."""
    end = date(2026, 7, 31)
    first_event = _accrual(
        ex_date=date(2025, 8, 1),
        pay_date=date(2025, 8, 8),
        gross=20.0,
        tax=-3.0,
        net=17.0,
        gross_rate=0.2,
    )
    second_event = _accrual(
        ex_date=date(2026, 2, 1),
        pay_date=date(2026, 2, 8),
        gross=30.0,
        tax=-4.5,
        net=25.5,
        gross_rate=0.3,
    )
    dataset = _dataset(
        cash=[
            _cash(payment_date=date(2025, 8, 8), amount=20.0),
            _cash(payment_date=date(2026, 2, 8), amount=30.0),
        ],
        accruals=[
            first_event,
            first_event.model_copy(),
            second_event,
            _accrual(
                symbol="FUND",
                conid="2",
                ex_date=date(2026, 3, 1),
                pay_date=date(2026, 3, 8),
                gross=20.0,
                tax=None,
                net=None,
                gross_rate=0.1,
                currency="SGD",
                fx_rate_to_base=0.75,
            ),
        ],
        positions=[
            _position(),
            _position(
                symbol="FUND",
                conid="2",
                asset_class="FUND",
                currency="SGD",
                quantity=200.0,
                position_value=2_400.0,
                fx_rate_to_base=0.75,
            ),
            _position(
                symbol="NOPAY",
                conid="3",
                quantity=50.0,
                position_value=5_000.0,
            ),
            _position(
                symbol="OPTION",
                conid="4",
                asset_class="OPT",
                quantity=1.0,
                position_value=200.0,
            ),
            _position(
                symbol="SHORT",
                conid="5",
                quantity=-10.0,
                position_value=-500.0,
                side="SHORT",
            ),
            _position(
                symbol="LOT_ROW",
                conid="6",
                quantity=10.0,
                position_value=1_000.0,
                level_of_detail="LOT",
            ),
        ],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        end,
        history_start_date=date(2025, 8, 1),
    )

    estimate = report.annual_estimate
    assert [holding.symbol for holding in estimate.holdings] == [
        "AAPL",
        "FUND",
        "NOPAY",
    ]
    aapl = estimate.holdings[0]
    assert aapl.trailing_gross_rate == pytest.approx(0.5)
    assert aapl.estimated_gross == pytest.approx(50.0)
    assert aapl.effective_tax_rate == pytest.approx(0.15)
    assert aapl.estimated_net == pytest.approx(42.5)
    fund = estimate.holdings[1]
    assert fund.estimated_gross == pytest.approx(20.0)
    assert fund.base_estimated_gross == pytest.approx(15.0)
    assert fund.estimated_net is None
    assert estimate.estimated_base_gross == pytest.approx(65.0)
    assert estimate.estimated_base_net is None
    assert estimate.eligible_base_market_value == pytest.approx(16_800.0)
    assert estimate.portfolio_estimated_gross_yield == pytest.approx(
        65.0 / 16_800.0
    )
    assert estimate.history_days_covered == 365
    assert estimate.complete_history is True


def test_annual_estimate_requires_complete_associated_tax_history_for_net() -> None:
    """Known tax on every trailing realized cash event is required for annual net."""
    dataset = _dataset(
        cash=[_cash(payment_date=date(2026, 6, 15))],
        accruals=[
            _accrual(
                ex_date=date(2026, 6, 8),
                pay_date=date(2026, 6, 15),
                tax=None,
                net=None,
            )
        ],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    holding = report.annual_estimate.holdings[0]
    assert holding.estimated_gross == 25.0
    assert holding.effective_tax_rate is None
    assert holding.estimated_net is None
    assert holding.base_estimated_net is None


def test_annual_estimate_rejects_tax_rate_above_one() -> None:
    """An invalid realized tax-to-gross ratio makes annual net unavailable."""
    dataset = _dataset(
        cash=[_cash(payment_date=date(2026, 6, 15))],
        accruals=[
            _accrual(
                ex_date=date(2026, 6, 8),
                pay_date=date(2026, 6, 15),
                gross=25.0,
                tax=-30.0,
                net=-5.0,
            )
        ],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    holding = report.annual_estimate.holdings[0]
    assert holding.effective_tax_rate is None
    assert holding.estimated_net is None


def test_annual_estimate_rejects_reused_withholding_tax_history() -> None:
    """Annual net stays unavailable when two events compete for one tax posting."""
    report = build_dividend_income_report(
        _two_dividends_one_withholding_dataset(include_position=True),
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    holding = report.annual_estimate.holdings[0]
    assert holding.effective_tax_rate is None
    assert holding.estimated_net is None


@pytest.mark.parametrize("ambiguous_kind", ["DIVIDEND", "WITHHOLDING"])
def test_annual_estimate_rejects_ambiguous_trailing_cash_lifecycle(
    ambiguous_kind: str,
) -> None:
    """Any unresolved trailing cash reversal makes annual net unreliable."""
    accrual_tax = -3.75 if ambiguous_kind == "DIVIDEND" else None
    cash = [
        _cash(payment_date=date(2026, 6, 15)),
        _cash(payment_date=date(2026, 7, 15)),
    ]
    if ambiguous_kind == "DIVIDEND":
        cash.append(_cash(payment_date=date(2026, 7, 20), code="RE"))
    else:
        cash.extend(
            [
                _cash(
                    amount=-3.75,
                    transaction_type="Withholding Tax",
                    payment_date=date(2026, 6, 15),
                ),
                _cash(
                    amount=-3.75,
                    transaction_type="Withholding Tax",
                    payment_date=date(2026, 7, 15),
                ),
                _cash(
                    amount=3.75,
                    transaction_type="Withholding Tax",
                    payment_date=date(2026, 7, 20),
                    code="RE",
                ),
            ]
        )
    dataset = _dataset(
        cash=cash,
        accruals=[
            _accrual(
                ex_date=date(2026, 6, 8),
                pay_date=date(2026, 6, 15),
                tax=accrual_tax,
                net=None,
            ),
            _accrual(
                ex_date=date(2026, 7, 8),
                pay_date=date(2026, 7, 15),
                tax=accrual_tax,
                net=None,
            ),
        ],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    holding = report.annual_estimate.holdings[0]
    assert holding.effective_tax_rate is None
    assert holding.estimated_net is None
    assert any(
        "ambiguous" in limitation.lower()
        and "reversal" in limitation.lower()
        for limitation in report.data_limitations
    )


def test_annual_estimate_deduplicates_exact_and_symbol_fallback_events() -> None:
    """One conid event repeated without conid contributes its per-share rate once."""
    exact = _accrual(conid="1", gross_rate=0.25)
    fallback = exact.model_copy(update={"conid": None})
    dataset = _dataset(
        accruals=[exact, fallback],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    holding = report.annual_estimate.holdings[0]
    assert holding.trailing_gross_rate == 0.25
    assert holding.estimated_gross == 25.0


def test_annual_estimate_tax_history_does_not_require_a_gross_rate() -> None:
    """Known realized gross and tax remain reliable when that accrual lacks a rate."""
    dataset = _dataset(
        cash=[_cash(payment_date=date(2026, 6, 15))],
        accruals=[
            _accrual(
                ex_date=date(2026, 2, 1),
                pay_date=date(2026, 2, 8),
                gross_rate=0.25,
                tax=None,
                net=None,
            ),
            _accrual(
                ex_date=date(2026, 6, 8),
                pay_date=date(2026, 6, 15),
                gross=25.0,
                tax=-3.75,
                net=21.25,
                gross_rate=None,
            ),
        ],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    holding = report.annual_estimate.holdings[0]
    assert holding.estimated_gross == 25.0
    assert holding.effective_tax_rate == pytest.approx(0.15)
    assert holding.estimated_net == pytest.approx(21.25)


def test_annual_estimate_keeps_each_accounts_latest_current_positions() -> None:
    """Different linked-account report dates do not drop eligible current holdings."""
    dataset = _dataset(
        positions=[
            _position(symbol="FIRST", conid="1", position_value=10_000.0),
            _position(
                symbol="SECOND",
                conid="2",
                position_value=5_000.0,
                report_date=date(2026, 7, 30),
                account_id="U2",
            ),
        ]
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        date(2026, 7, 31),
        history_start_date=date(2025, 8, 1),
    )

    assert [holding.symbol for holding in report.annual_estimate.holdings] == [
        "FIRST",
        "SECOND",
    ]
    assert report.annual_estimate.eligible_base_market_value == 15_000.0


def test_annual_estimate_marks_a_120_day_observed_run_rate_incomplete() -> None:
    """Partial history remains an unscaled lower bound with exact covered days."""
    end = date(2026, 7, 31)
    dataset = _dataset(
        accruals=[
            _accrual(
                ex_date=date(2026, 6, 1),
                pay_date=date(2026, 6, 8),
                gross_rate=0.5,
                gross=50.0,
                tax=None,
                net=None,
            )
        ],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 7, 1),
        end,
        coverage_note="Only a 120-day Flex window was available.",
        history_start_date=end.replace(month=4, day=3),
    )

    estimate = report.annual_estimate
    assert estimate.holdings[0].estimated_gross == 50.0
    assert estimate.estimated_base_gross == 50.0
    assert estimate.history_days_covered == 120
    assert estimate.complete_history is False


def test_future_requested_end_uses_separate_annual_history_cutoff() -> None:
    """Future expected rows remain visible while annual history stops at today."""
    today = date(2026, 7, 31)
    future_end = date(2026, 8, 31)
    historical = _accrual(
        ex_date=date(2025, 9, 1),
        pay_date=date(2025, 9, 8),
        gross_rate=0.2,
        gross=20.0,
        tax=None,
        net=None,
    )
    future = _accrual(
        ex_date=date(2026, 8, 10),
        pay_date=date(2026, 8, 15),
        gross_rate=0.9,
        gross=90.0,
        tax=None,
        net=None,
    )
    dataset = _dataset(
        accruals=[historical, future],
        open_accruals=[future.model_copy()],
        positions=[_position()],
    )

    report = build_dividend_income_report(
        dataset,
        date(2026, 8, 1),
        future_end,
        history_start_date=date(2025, 9, 1),
        history_end_date=today,
    )

    assert [line.payment_date for line in report.expected_dividends] == [
        date(2026, 8, 15)
    ]
    estimate = report.annual_estimate
    assert estimate.holdings[0].trailing_gross_rate == pytest.approx(0.2)
    assert estimate.history_days_covered == 334
    assert estimate.complete_history is False
