# Doliv Lab — smoke checklist

Полный HOWTO: [HOW_TO.md](./HOW_TO.md).

After each phase: ~5–10 min. Lab only (`localhost:5175` / `:8002`).

## Seed logins

| Login | Password | Role |
|-------|----------|------|
| owner | owner123 | owner |
| admin | admin123 | admin |
| teamlead1 | teamlead123 | teamlead |
| trader1 | trader123 | trader (+1000 USDT **личный** токен) |
| merchant1 | merchant123 | trader exempt |
| doliv1 | doliv123 | dolivshchik |

## Checklist

1. **Рабочий курс** — admin Manual / Rapira / Fixed.
2. **Пул тимлида** — trader % ≤ pool; TL keep на закрытии.
3. **Депозит трейдера** — заявка пополнить/вывести (сеть + адрес); admin **Мост / апрувы** → OK. Self-deposit выключен. Fee $3 USDT / $2 BTC|LTC.
4. **Выплаты** — admin создаёт payout job; trader **Выплаты** claim за 15 мин (сумма ≤ float).
5. **Merchant API** — создать partner keys; `docs/INTEGRATION.md` create_order_payin (нужна карта в работе).
6. **Bridge** — выпустить X-Bridge-Key; `GET /bridge/card-balances`.
7. Карты / залив / коридоры / C2C·СБП — как раньше.

## Auto

```bash
cd ~/Desktop/doliv-lab/backend
pytest -q tests/test_bridge_core.py tests/test_trader_wallet_deposit.py \
  tests/test_merchant_payin.py tests/test_teamlead_pool.py tests/test_deposit_float.py
```

See [INTEGRATION.md](./INTEGRATION.md), [SANDBOX.md](./SANDBOX.md).
