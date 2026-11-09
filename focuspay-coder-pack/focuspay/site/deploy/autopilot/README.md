# Autopilot wallet dedic (phase 2)

## Host

- Debian 13, 8 GB RAM, 100 GB NVMe
- Users: `focuspay-signer` (service), no login shell

## WireGuard

Prod (`10.8.0.1`) ↔ dedic (`10.8.0.2`). UDP 51820 only from prod IP.

```bash
apt install wireguard ufw
ufw default deny incoming
ufw allow from 153.80.249.77 to any port 51820 proto udp
ufw enable
```

Signer binds **only** on `wg0`:

```ini
# /etc/focuspay/signer.env
SIGNER_SECRET_KEY=...
SIGNER_API_KEY=focuspay-main
BIND_HOST=10.8.0.2
BIND_PORT=9000
DRY_RUN=true

# Лимиты на самом дедике (второй рубеж, не зависит от основного сервера)
MAX_TX_BTC=0.05
MAX_TX_LTC=20.0
DAILY_CAP_BTC=0.2
DAILY_CAP_LTC=60.0
# Актуальные потолки после сохранения в /x8/autopilot уходят на подписант
# через POST /v1/policy (файл policy_overrides.json). Env — старт и запас.
FEE_PCT_CAP=5
ADDRESS_BLOCKLIST=

# RPC нод (rpcuser/rpcpassword из bitcoin.conf / litecoin.conf, wallet = hot)
BTC_RPC_URL=http://127.0.0.1:8332
BTC_RPC_USER=...
BTC_RPC_PASSWORD=...
BTC_RPC_WALLET=hot
LTC_RPC_URL=http://127.0.0.1:9332
LTC_RPC_USER=...
LTC_RPC_PASSWORD=...
LTC_RPC_WALLET=hot
```

Состояние signer'а (идемпотентность по `request_id`, anti-replay подписей)
хранится в `/var/lib/focuspay-signer/signer.sqlite3`. **Не удалять этот файл**:
без него signer забудет, какие выплаты уже ушли. Бэкапить вместе с кошельком.

Все эндпоинты, включая `/v1/health`, требуют HMAC-подпись. Ответ `unknown`
значит «отправка могла состояться» — такую выплату основной сервер не
переотправляет и не возвращает на баланс, её проверяет человек по ноде.

`/v1/health` отдаёт ещё и `nodes` (блоки, заголовки, `syncing`). `/v1/deposit-address`
отдаёт следующий свободный адрес пополнения. Если на текущий уже приходили монеты
(`getreceivedbyaddress`, включая неподтверждённые), подписант берёт следующий
`getnewaddress` и показывает его. Прежние адреса остаются в кошельке `hot` и в sqlite:
перевод на них зачисляется в общий баланс, выплата тратит выходы со всех адресов сразу.
`POST /v1/deposit-address` с `{"coin":"btc"}` или `ltc` меняет показанный адрес до прихода
монет. В ответе `addresses` — текущие, `known` — все, включая сменённые.
Если RPC настроен, `/v1/balance` показывает настоящие балансы и при `DRY_RUN=true`
(холостыми остаются только отправки).
Всё это выводит страница `/x8/autopilot` через `GET /api/admin/autopilot/overview`.

## Пополнение горячего кошелька

Внешнее пополнение bitcoind считает `untrusted_pending`: до подтверждения его нет в
`spendable`, а `sendtoaddress` его не тратит.

- **Ожидание (по умолчанию).** Если денег не хватает, но пополнение в пути покрывает выплату,
  автопилот её не отдаёт оператору, а ждёт до `auto_payout_wait_funds_max_min` минут (120).
  Владельцу уходит одно сообщение. Позже — `funds_wait_timeout`, заявка уходит оператору.
- **Доверенное пополнение.** `TRUSTED_TOPUPS_ENABLED=true` + `TRUSTED_TOPUP_MAX_BTC` в
  `signer.env` (только BTC) и тумблер «Доверенные пополнения» на `/x8/autopilot`. Админ вставляет
  txid своего перевода — подписант тратит его выходы через `send` с явными `inputs`
  (`include_unsafe` не включаем, чужие неподтверждённые монеты не берём). Сдача наших выплат
  от такого родителя тоже тратится (txid из `payouts`). Комиссия выплат подтягивает родителя.
- Пополнение с выплатами сверху Bitcoin Core через `bumpfee` не ускорит («has descendants»).
  Если его всё же заменили или оно выпало из mempool — статус `conflicted`/`dropped`, тревога
  владельцу: выплаты-потомки тоже пропадут, разбирать по ноде.
- Из одного неподтверждённого пополнения в v31 уходит ~50 выплат подряд, дальше
  `mempool_chain_limit` — явный отказ, выплата ждёт блока.
- «Вернуть в автопилот» — для заявок, ушедших оператору из-за нехватки денег, если хеша нет и
  оператор не отправлял с кошелька проекта. Повтор идёт с `request_id` `order:{id}-rN`.

Регтест: `BITCOIND=/path/to/bitcoind python scripts/regtest_trusted_topups.py` из
`site/focuspay-signer/`.

## Nodes

```ini
# bitcoind — prune=10000, rpcbind=127.0.0.1
# litecoind — same
```

Wallet `hot` via `createwallet` + descriptor. Fund from cold manually.

## systemd

Unit `focuspay-signer.service`: `ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes`.

Prod `.env`:

```
SIGNER_BASE_URL=http://10.8.0.2:9000
SIGNER_SECRET_KEY=...
SIGNER_API_KEY=focuspay-main
```

Apply SQL: `site/exchange-backend/migrations/add_autopilot.sql` (+ `add_merchant_attribution.sql`, `add_project_wallet_payout.sql`).

## Ручные заявки с кошелька проекта

Тумблер `manual_payout_wallet` (`operator` | `project`) на `/x8/autopilot`, раздел «Ручные заявки».
В режиме `project` финансовый оператор по BTC/LTC не вставляет хеш: «Отправить» → окно
(клиент, адрес, сумма, комиссия, остаток, лимит) → код 2FA → `POST /api/operator/orders`
с `wallet_send` или `POST /api/operator/orders/{id}/wallet-send` для переданных заявок.

- Сумма считается сервером и подписана в токене окна (120 с); изменилась форма или курс > 1% — 409.
- Код 2FA одноразовый (`operator_accounts.totp_last_step`), 3 ошибки — блок на 15 минут и сообщение админу.
- Лимиты: `manual_wallet_payout_max_rub` за раз, `manual_wallet_payout_operator_daily_rub` на оператора
  (`payout_requests.operator_id`), плюс общий `auto_payout_daily_cap_rub`.
- Адрес не должен принадлежать другому клиенту, оператору или самому проекту.
- Подписант в DRY_RUN — отправка запрещена (иначе заявка закрылась бы фиктивным хешем).
- Отказ подписанта — новая заявка отменяется, переданная остаётся у оператора. Нет ответа —
  заявка заморожена, повтор и ручной хеш запрещены, админу уходит сообщение.
- Каждая отправка пишется на смену оператора (`auto_recon_entries.kind = 'project_wallet_payout'`).

Комиссии сети — таблица `network_fees`: с кошелька проекта из ответа подписанта, по хешам
операторов фоном из mempool.space / litecoinspace (запасной — blockchair) / tronscan, по 20 tx в 10 минут.
