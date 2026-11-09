# Merchant / Partner Integration (Lab)

Подключение к выдаче реквизитов по API — тот же паттерн, что у типичного Merchant payin (HMAC): create → poll get → cancel.

База lab: `http://localhost:8002` (или ваш `API_URL`).

## 1. Ключи

Админ: **Мост / апрувы** → «Создать ключи» Merchant partner  
или `POST /admin/merchant-partners` `{ "name": "partner-x" }` → ответ: `api_key`, `secret` (secret показывается один раз).

## 2. Подпись

Каждый POST:

1. Body = JSON **без пробелов** (`separators=(",", ":")`).
2. `timestamp` = unix seconds (string).
3. `signature` = `HMAC_SHA256(secret, timestamp + body)` hex.
4. Headers:
   - `X-API-Key: <api_key>`
   - `X-Timestamp: <timestamp>`
   - `X-Signature: <signature>`
   - `Content-Type: application/json`

## 3. Endpoints

### Create payin

`POST /api_merchant/create_order_payin`

```json
{
  "token": "P2P",
  "sub_token": "SBPRUB",
  "fingerprint": "client-1",
  "client_transaction_id": "order-123",
  "amount": 5000,
  "callback_url": "https://your.example/callback"
}
```

Ответ (успех): `uuid`, `bill.reciver` (карта/телефон), `bill.bankName`, `bill.holderName`, `status_pending`.

Если нет принимающей карты: `status_pending=error`.

### Get order

`POST /api_merchant/get_order` body `{ "uuid": "..." }`

### Cancel

`POST /api_merchant/cancel_order_payin` body `{ "uuid": "..." }`

## 4. Curl example (Python sign)

```python
import hashlib, hmac, json, time, urllib.request

BASE = "http://localhost:8002"
API_KEY = "..."
SECRET = "..."

payload = {
    "token": "P2P",
    "sub_token": "SBPRUB",
    "fingerprint": "1",
    "client_transaction_id": "demo-1",
    "amount": 5000,
    "callback_url": "",
}
body = json.dumps(payload, separators=(",", ":"))
ts = str(int(time.time()))
sig = hmac.new(SECRET.encode(), (ts + body).encode(), hashlib.sha256).hexdigest()
req = urllib.request.Request(
    f"{BASE}/api_merchant/create_order_payin",
    data=body.encode(),
    headers={
        "Content-Type": "application/json",
        "X-API-Key": API_KEY,
        "X-Timestamp": ts,
        "X-Signature": sig,
    },
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
```

## 5. Bridge FocusPay → Doliv (выплаты)

Сервисный ключ: admin «Выпустить X-Bridge-Key».

| Method | Path | Header |
|--------|------|--------|
| POST | `/bridge/payout-jobs` | `X-Bridge-Key` |
| GET | `/bridge/card-balances` | `X-Bridge-Key` |
| GET | `/bridge/payout-jobs/{id}` | `X-Bridge-Key` |
| POST | `/bridge/payout-jobs/{id}/events` | `X-Bridge-Key` |

Body job: `{ "amount_rub": 10000, "pay_method": "sbp", "requisites": {...}, "source": "freelancer", "external_ref": "fp-123" }`.

Env для FocusPay (adapter): `DOLIV_BRIDGE_URL`, `DOLIV_BRIDGE_KEY`.

FocusPay ops:
- `GET /api/operator/doliv/card-balances`
- `POST /api/operator/orders/{order_id}/push-doliv-payout` (SELL → Doliv)

Внештатник:
- `POST /api/exchanger/payouts/rub-card` `{ amount_rub, pay_method, phone|card_number }`

## 6. Статус ордера + callback

`POST /api_merchant/payin_set_status` body `{ "uuid": "...", "status": "paid" }`  
→ партнёру POST на `callback_url`: `{ event, uuid, status, amount, bill }`.

## 7. Смена с Payfast

Партнёру: тот же create/get/cancel + HMAC. Меняется только `BASE` URL и ключи. Реквизиты больше не раздаются вручную в чат.
