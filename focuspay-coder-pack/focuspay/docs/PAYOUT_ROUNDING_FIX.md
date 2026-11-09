# BUY payout rounding — 2026-09-15

Local fix; not deployed.

Incident: a stored payout of 0.60472272 LTC for 3472 RUB at rate
5741.474412 was rejected as `crypto_exceeds_paid`. The exact quotient is
0.6047227159531231; eight-place rounding exceeded the old 1e-9 epsilon.

`bot/tg_bot_btc/services/buy_payout_validate.py` now calculates the payout
ceiling from the original monetary fields using Decimal. It accepts the
larger of the exact ceiling and its eight-place half-even rounding, with
only 1e-12 numerical slack. The requested payout itself is not rounded.
Cashback and exchange discount remain included; no percentage tolerance
is introduced. Creation/clamping and existing order records are unchanged.

Regression coverage includes the incident, the next decimal unit (rejected),
real overpayment (rejected), exact/unrounded values, and discount/cashback.

Verification from `bot/tg_bot_btc/`:

```bash
.venv/bin/python -m unittest tests.test_buy_payout_rounding tests.test_financial_safety tests.test_balance_buy_discount tests.test_manual_buy_payout
```

Result: 65 tests passed. No order recovery, payout, production deployment,
or service restart was performed.
