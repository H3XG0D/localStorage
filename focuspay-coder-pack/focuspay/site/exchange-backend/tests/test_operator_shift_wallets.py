"""Tests for operator shift wallet validation."""

from operator_shift_wallets import ShiftBalanceEntry, validate_shift_balances


def test_validate_shift_balances_requires_all_cryptos():
    try:
        validate_shift_balances([ShiftBalanceEntry(crypto="usdt", amount=1.0)])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "USDT" in str(e)


def test_validate_shift_balances_accepts_zero():
    result = validate_shift_balances(
        [
            ShiftBalanceEntry(crypto="usdt", amount=10.5),
            ShiftBalanceEntry(crypto="btc", amount=0),
            ShiftBalanceEntry(crypto="trx", amount=0),
            ShiftBalanceEntry(crypto="ltc", amount=0),
        ]
    )
    assert len(result) == 4
    assert result[0].crypto == "usdt"
    assert result[0].amount == 10.5
