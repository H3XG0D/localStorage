/** Тексты HMAC API реквизитов — кабинет внештатника и админка. */

export const EXCHANGER_HMAC_PATH = "/api/exchanger/v1";
export const EXCHANGER_HMAC_SECRET_PLACEHOLDER = "$SECRET";
export const EXCHANGER_HMAC_KEY_PLACEHOLDER = "$API_KEY";

export const EXCHANGER_HMAC_STEPS: Array<{ n: string; title: string; text: string }> = [
  {
    n: "1",
    title: "Ключ",
    text: "Ключ выдаёт администратор. Секрет показывают один раз — сохраните. Подпись: HMAC-SHA256(secret, timestamp + сырое тело), hex строчными.",
  },
  {
    n: "2",
    title: "Создать сделку",
    text: "POST /deals с amount_rub (или amount_crypto), client_transaction_id и fingerprint. В ответе bill и client_pays_rub — эту сумму покажите клиенту без округлений. Повтор с тем же client_transaction_id вернёт ту же сделку.",
  },
  {
    n: "3",
    title: "Оплата и чек",
    text: "Клиент перевёл → POST /deals/{id}/paid с {}. Затем POST /deals/{id}/receipt с публичным https URL PDF (не base64). Канон: create → paid → receipt → ждёте credited.",
  },
  {
    n: "4",
    title: "Зачисление (callback)",
    text: "Мы POST на ваш callback_url с event=credited, event_id и подписью X-Timestamp + X-Signature (тот же секрет). Обязательно проверьте подпись и дедупьте по event_id — доставка at-least-once с повторами. Либо опрашивайте GET /deals/{id}: confirmed = уже на балансе.",
  },
  {
    n: "5",
    title: "Отмена",
    text: "Клиент не заплатил — POST /deals/{id}/cancel с {}. Только awaiting_receipt и пока чек не отправлен. Иначе 400. В callback будет event=cancelled.",
  },
  {
    n: "6",
    title: "Статистика клиента (желательно)",
    text: "Передайте client_stat в create или один раз POST /clients/stat по fingerprint — в споре клиент не выглядит «новым». ФИО, телефон и Telegram не слать. GET /deals/{id}/check — для отладки карточки, не обязателен в интеграции.",
  },
];

export const EXCHANGER_HMAC_HEADERS: Array<{ name: string; value: string }> = [
  { name: "X-API-Key", value: "Ключ, который выдал администратор площадки" },
  { name: "X-Timestamp", value: "Unix-секунды UTC. Часы не должны уезжать больше чем на 5 минут." },
  { name: "X-Signature", value: "HMAC-SHA256(secret, timestamp + сырое тело), hex строчными буквами" },
  { name: "Content-Type", value: "Для POST — application/json" },
];

export const EXCHANGER_HMAC_CREATE_FIELDS: Array<{ name: string; req: string; desc: string }> = [
  { name: "amount_rub", req: "одно из", desc: "Сумма ввода в ₽ — как в кабинете: на баланс или оборот, смотря какая у вас наценка." },
  { name: "amount_crypto + crypto", req: "одно из", desc: "Вместо рублей: например 1.5243 и ltc / usdt / btc / trx. Курс Рапиры считаем мы." },
  { name: "sub_token", req: "нет", desc: "SBPRUB — СБП, CARDRUB — карта. Если не передать, будет СБП." },
  { name: "client_transaction_id", req: "лучше да", desc: "Ваш номер заказа. Повтор с тем же id вернёт ту же сделку, новую не откроет." },
  { name: "fingerprint", req: "лучше да", desc: "Id вашего покупателя. Без него все клиенты выглядят как один — карты начнут путаться, статистика не привяжется." },
  { name: "callback_url", req: "нет", desc: "https://… — пришлём POST JSON, когда зачислим, отменим или продлим окно." },
  { name: "note", req: "нет", desc: "Ваша пометка. Клиент её не увидит." },
  { name: "client_stat", req: "лучше да", desc: "Сводка по этому покупателю: paid_orders, buy_paid/buy_failed, turnover_rub. Иначе сразу POST /deals/{id}/client-stat." },
];

export const EXCHANGER_HMAC_DEAL_FIELDS: Array<{ name: string; desc: string }> = [
  { name: "deal_id / id", desc: "Наш номер. Нужен для paid, receipt и cancel." },
  { name: "status", desc: "awaiting_receipt → pending → confirmed или cancelled." },
  { name: "client_pays_rub", desc: "Сколько должен заплатить клиент. Эту сумму и показывайте." },
  { name: "amount_rub", desc: "Сумма ввода магазина (до или после наценки — как у вас в кабинете)." },
  { name: "bill", desc: "Реквизит для клиента: bank, reciver (телефон или карта), fio. Служебные поля Payfast сюда не входят." },
  { name: "payment.bill", desc: "То же внутри payment. Берите bill сверху или отсюда." },
  { name: "payment_text", desc: "Готовый текст для клиента: реквизит, сумма, срок, запрет МТС Банка и Уралсиба, правила чека." },
  { name: "expires_at", desc: "До этого момента клиент должен успеть заплатить." },
  { name: "needs_operator_video", desc: "true — PDF не приняли, нужно видео экрана. PDF больше не принимаем." },
  { name: "client_stat", desc: "Последняя сводка, которую вы прислали. GET /deals/{id}/check отдаёт её в виде карточки /check." },
];

export const EXCHANGER_HMAC_STATUSES: Array<{ status: string; desc: string }> = [
  { status: "awaiting_receipt", desc: "Реквизит выдан. Покажите bill и сумму клиенту." },
  { status: "pending", desc: "Чек приняли, ждём оператора." },
  { status: "confirmed", desc: "Зачислили на баланс. В callback будет event=credited." },
  { status: "cancelled", desc: "Отмена из API или кабинета. POST /deals/{id}/cancel, пока awaiting_receipt и нет чека. В callback — event=cancelled." },
];

export const EXCHANGER_HMAC_ERRORS: Array<{ code: string; detail: string; why: string }> = [
  { code: "401", detail: "X-API-Key, X-Timestamp, X-Signature required", why: "Нет одного из заголовков" },
  { code: "401", detail: "Invalid API key / Shop disabled", why: "Ключ отозван или магазин выключен" },
  { code: "401", detail: "Timestamp expired", why: "Часы уехали больше чем на 5 минут. Поставьте NTP." },
  { code: "401", detail: "Invalid signature", why: "Подписали не ту строку: нужен timestamp + сырой JSON, как в теле" },
  { code: "401", detail: "Replay rejected", why: "Этот timestamp и это тело мы уже принимали" },
  { code: "400", detail: "amount_rub or amount_crypto required", why: "Нет суммы" },
  { code: "404", detail: "Сделка не найдена", why: "Чужой deal_id или опечатка" },
  { code: "400", detail: "отмена невозможна", why: "Чек уже отправлен или статус не awaiting_receipt" },
  { code: "503", detail: "Курс …/RUB недоступен", why: "Рапира не ответила — повторите или передайте amount_rub" },
];

export const EXCHANGER_HMAC_ENDPOINTS: Array<{ method: string; path: string; body: string; desc: string }> = [
  {
    method: "POST",
    path: "/deals",
    body: '{"amount_rub":1000,"sub_token":"SBPRUB","client_transaction_id":"order-1","fingerprint":"buyer-42","callback_url":"https://shop.example/hook"}',
    desc: "Открыть сделку: bill и сумма к оплате.",
  },
  {
    method: "GET",
    path: "/deals/{id}",
    body: "",
    desc: "Канон статуса по нашему id. Тела нет, подпись по timestamp+\"\".",
  },
  {
    method: "GET",
    path: "/deals?client_transaction_id=order-1",
    body: "",
    desc: "Найти по вашему номеру заказа (альтернатива GET /deals/{id}).",
  },
  {
    method: "POST",
    path: "/deals/get",
    body: '{"deal_id":123}',
    desc: "Совместимость: deal_id или client_transaction_id в JSON.",
  },  {
    method: "POST",
    path: "/deals/{id}/paid",
    body: "{}",
    desc: "Клиент оплатил. Дальше — чек.",
  },
  {
    method: "POST",
    path: "/deals/{id}/receipt",
    body: '{"file":"https://cdn.example/check.pdf"}',
    desc: "Публичный http(s) URL PDF. Не base64.",
  },
  {
    method: "POST",
    path: "/deals/{id}/cancel",
    body: "{}",
    desc: "Отменить, пока awaiting_receipt и чек не отправлен.",
  },
  {
    method: "POST",
    path: "/deals/{id}/client-stat",
    body: '{"paid_orders":7,"total_orders":14,"buy_paid":7,"buy_failed":3,"conversion_pct":70,"turnover_rub":84500,"first_order_at":"2026-03-12T00:00:00+00:00","last_paid_at":"2026-09-06T12:00:00+00:00"}',
    desc: "Сводка по покупателю этой сделки. То, что увидит /check uuid в чате Payfast.",
  },
  {
    method: "POST",
    path: "/clients/stat",
    body: '{"fingerprint":"buyer-42","paid_orders":7,"buy_paid":7,"buy_failed":3,"turnover_rub":84500}',
    desc: "Та же сводка по fingerprint, даже без открытой сделки. Подставим в следующие.",
  },
  {
    method: "GET",
    path: "/deals/{id}/check",
    body: "",
    desc: "Проверить, какая карточка уйдёт в /check: status как у нашей заявки + числа client_stat.",
  },
];

export const EXCHANGER_HMAC_CLIENT_STAT_FIELDS: Array<{ name: string; desc: string }> = [
  { name: "paid_orders", desc: "Сколько раз этот клиент у вас успешно оплатил." },
  { name: "total_orders", desc: "Заявок всего. Если не передать — buy_paid + buy_failed." },
  { name: "buy_paid", desc: "Успешные покупки. Знаменатель конверсии вместе с buy_failed." },
  { name: "buy_failed", desc: "Отмены и просрочки." },
  { name: "conversion_pct", desc: "100 × buy_paid / (buy_paid + buy_failed), одно десятичное. Если знаменатель 0 — не передавайте." },
  { name: "turnover_rub", desc: "Сумма успешных оплат в ₽." },
  { name: "first_order_at", desc: "ISO-8601 UTC, первая заявка." },
  { name: "last_paid_at", desc: "ISO-8601 UTC, последняя успешная оплата." },
];

export const EXCHANGER_HMAC_CLIENT_STAT_BODY = `{
  "paid_orders": 7,
  "total_orders": 14,
  "buy_paid": 7,
  "buy_failed": 3,
  "conversion_pct": 70.0,
  "turnover_rub": 84500,
  "first_order_at": "2026-03-12T00:00:00+00:00",
  "last_paid_at": "2026-09-06T12:00:00+00:00"
}`;

export const EXCHANGER_HMAC_CALLBACK_EXAMPLE = `{
  "event": "credited",
  "event_id": "ext-123-credited",
  "deal_id": 123,
  "id": 123,
  "client_transaction_id": "order-1",
  "status": "confirmed",
  "amount_rub": 1000,
  "client_pays_rub": 1150,
  "principal_usdt": 12.35,
  "expires_at": "2026-08-20T12:20:00+00:00"
}`;

export const EXCHANGER_HMAC_CREATE_CRYPTO_BODY =
  '{"amount_crypto":1.5243,"crypto":"ltc","sub_token":"SBPRUB","client_transaction_id":"order-1","fingerprint":"buyer-42"}';

export function exchangerHmacBaseUrl(origin?: string): string {
  const base = (origin || (typeof window !== "undefined" ? window.location.origin : "https://focuspay.org")).replace(/\/$/, "");
  return `${base}${EXCHANGER_HMAC_PATH}`;
}

function resolveKey(apiKey?: string | null): string {
  return (apiKey || "").trim() || EXCHANGER_HMAC_KEY_PLACEHOLDER;
}

export function exchangerHmacCurlExample(apiKey: string, origin?: string): string {
  const url = exchangerHmacBaseUrl(origin);
  const key = resolveKey(apiKey);
  return `TS=$(date +%s)
BODY='{"amount_rub":1000,"sub_token":"SBPRUB","client_transaction_id":"order-1","fingerprint":"buyer-42"}'
SIG=$(printf '%s%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS ${url}/deals \\
  -H 'Content-Type: application/json' \\
  -H "X-API-Key: ${key}" \\
  -H "X-Timestamp: $TS" \\
  -H "X-Signature: $SIG" \\
  -d "$BODY"

# Отмена, пока нет чека. DEAL_ID — из ответа создания.
TS=$(date +%s)
BODY='{}'
SIG=$(printf '%s%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS ${url}/deals/DEAL_ID/cancel \\
  -H 'Content-Type: application/json' \\
  -H "X-API-Key: ${key}" \\
  -H "X-Timestamp: $TS" \\
  -H "X-Signature: $SIG" \\
  -d "$BODY"

# Сводка клиента этой сделки
TS=$(date +%s)
BODY='{"paid_orders":7,"buy_paid":7,"buy_failed":3,"turnover_rub":84500}'
SIG=$(printf '%s%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sS ${url}/deals/DEAL_ID/client-stat \\
  -H 'Content-Type: application/json' \\
  -H "X-API-Key: ${key}" \\
  -H "X-Timestamp: $TS" \\
  -H "X-Signature: $SIG" \\
  -d "$BODY"`;
}

export function exchangerHmacPythonExample(apiKey?: string | null, origin?: string): string {
  const key = resolveKey(apiKey);
  const base = exchangerHmacBaseUrl(origin);
  return `import hmac, hashlib, time, json, requests

API_KEY = "${key}"
SECRET  = "${EXCHANGER_HMAC_SECRET_PLACEHOLDER}"
BASE    = "${base}"

def focuspay(path, body=None, method=None):
    method = method or ("POST" if body is not None else "GET")
    ts = str(int(time.time()))
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
    sig = hmac.new(SECRET.encode(), (ts + body_str).encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-API-Key": API_KEY,
        "X-Signature": sig,
        "X-Timestamp": ts,
        "Content-Type": "application/json",
    }
    r = requests.request(
        method, BASE + path,
        data=body_str.encode() if body_str else None,
        headers=headers, timeout=20,
    )
    return r.status_code, r.json()

# Создать сделку (₽). Для крипты: amount_crypto=1.5243, crypto="ltc"
code, deal = focuspay("/deals", {
    "amount_rub": 1000,
    "sub_token": "SBPRUB",
    "client_transaction_id": "order-1",
    "fingerprint": "buyer-42",
    "callback_url": "https://shop.example/hook",
})
print(code, deal)
deal_id = deal["deal_id"]

# Статус
print(focuspay(f"/deals/{deal_id}"))

# Отмена, пока нет чека
# print(focuspay(f"/deals/{deal_id}/cancel", {}))

# Клиент оплатил, затем чек (публичный URL)
print(focuspay(f"/deals/{deal_id}/paid", {}))
print(focuspay(f"/deals/{deal_id}/receipt", {"file": "https://cdn.example/check.pdf"}))

# Сводка клиента — без неё /check uuid покажет «нового»
print(focuspay(f"/deals/{deal_id}/client-stat", {
    "paid_orders": 7,
    "total_orders": 14,
    "buy_paid": 7,
    "buy_failed": 3,
    "conversion_pct": 70.0,
    "turnover_rub": 84500,
    "first_order_at": "2026-03-12T00:00:00+00:00",
    "last_paid_at": "2026-09-06T12:00:00+00:00",
}))
print(focuspay(f"/deals/{deal_id}/check"))
`;
}

export function exchangerHmacGuideLines(origin?: string): string[] {
  const base = exchangerHmacBaseUrl(origin);
  return [
    `База: ${base}`,
    "Подпись: HMAC-SHA256(secret, timestamp + сырое тело запроса).",
    "Заголовки: X-API-Key, X-Timestamp (unix-секунды), X-Signature.",
    "Часы ±5 минут. Тот же timestamp с тем же телом второй раз не пройдёт.",
    "GET тоже подписывается: тела нет, подписываете только timestamp.",
    "sub_token: SBPRUB (СБП) или CARDRUB (карта).",
    "fingerprint — id вашего клиента, иначе все покупатели выглядят как один.",
    `Вместо amount_rub можно amount_crypto и crypto, например ${EXCHANGER_HMAC_CREATE_CRYPTO_BODY}.`,
    "callback_url (необязательно): POST JSON event=credited|cancelled|extended.",
    "Отмена: POST /deals/{id}/cancel с телом {}, пока awaiting_receipt и нет чека.",
    "Статистика клиента: POST /deals/{id}/client-stat или поле client_stat при создании. Без fingerprint все покупатели сливаются.",
    "GET /deals/{id}/check — то, что увидит Payfast по /check uuid.",
    "В ответе: deal_id, bill (банк/телефон/карта), payment_text, expires_at, payment.",
  ];
}

function mdTable(headers: string[], rows: string[][]): string {
  const head = `| ${headers.join(" | ")} |`;
  const sep = `| ${headers.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${row.map((c) => c.replace(/\|/g, "\\|")).join(" | ")} |`).join("\n");
  return `${head}\n${sep}\n${body}`;
}

export function exchangerHmacMarkdown(origin?: string, apiKey?: string | null): string {
  const base = exchangerHmacBaseUrl(origin);
  const key = resolveKey(apiKey);
  return `# FocusPay — API реквизитов для магазина

REST. Каждый запрос — три заголовка и HMAC-SHA256. Здесь только приём оплаты: выводов и апелляций в этом API нет.

**Base URL:** \`${base}\`

## 1. Как это работает

${EXCHANGER_HMAC_STEPS.map((s) => `${s.n}. **${s.title}.** ${s.text}`).join("\n")}

## 2. С чего начать (Python)

Подставьте \`API_KEY\` и \`SECRET\`, которые выдал администратор площадки.

\`\`\`python
${exchangerHmacPythonExample(key, origin).trim()}
\`\`\`

> Часы сервера: \`X-Timestamp\` принимаем, если расхождение не больше ±5 минут. Поставьте NTP.

Curl:

\`\`\`bash
${exchangerHmacCurlExample(key, origin)}
\`\`\`

## 3. Подпись

Каждый запрос, даже GET, идёт с этими заголовками:

${mdTable(
    ["Header", "Значение"],
    EXCHANGER_HMAC_HEADERS.map((h) => [`\`${h.name}\``, h.value]),
  )}

Правила:

- Строка подписи — вплотную \`timestamp + body\`, без пробела и перевода строки.
- GET или пустое тело: подписываете только timestamp (тело — пустая строка).
- Подписывайте ровно ту JSON-строку, которую отправляете. Пробелы и порядок ключей важны. Проще собрать строку один раз и её же отправить.

## 4. Справочники

### sub_token

${mdTable(
    ["Значение", "Смысл"],
    [
      ["`SBPRUB`", "СБП, в bill.reciver телефон"],
      ["`CARDRUB`", "Карта, в bill.reciver номер"],
    ],
  )}

### status

${mdTable(
    ["status", "Смысл"],
    EXCHANGER_HMAC_STATUSES.map((s) => [`\`${s.status}\``, s.desc]),
  )}

### crypto

\`usdt\`, \`btc\`, \`ltc\`, \`trx\`. Нужен только если передаёте \`amount_crypto\`.

## 5. Создать сделку — POST /deals

${mdTable(
    ["Поле", "Обяз.", "Описание"],
    EXCHANGER_HMAC_CREATE_FIELDS.map((f) => [`\`${f.name}\``, f.req, f.desc]),
  )}

Пример в рублях — в Python выше. Пример в крипте:

\`\`\`json
${EXCHANGER_HMAC_CREATE_CRYPTO_BODY}
\`\`\`

Ответ \`201\`. Смотрите \`deal_id\`, \`bill\`, \`client_pays_rub\`, \`expires_at\`.

## 6. Объект сделки

Так выглядит сделка после создания и при запросе статуса.

${mdTable(
    ["Поле", "Описание"],
    EXCHANGER_HMAC_DEAL_FIELDS.map((f) => [`\`${f.name}\``, f.desc]),
  )}

## 7. Эндпоинты

${mdTable(
    ["Метод", "Путь", "Зачем"],
    EXCHANGER_HMAC_ENDPOINTS.map((e) => [`\`${e.method}\``, `\`${e.path}\``, e.desc]),
  )}

- \`POST /deals/{id}/paid\` — тело \`{}\`.
- \`POST /deals/{id}/receipt\` — \`{"file":"https://...pdf"}\`. Файл должен открываться без авторизации. Мы его скачиваем.
- \`POST /deals/{id}/cancel\` — тело \`{}\`. Пока \`awaiting_receipt\` и чек не отправлен.
- \`POST /deals/{id}/client-stat\` — сводка по покупателю. Можно сразу в \`POST /deals\` полем \`client_stat\`.
- \`GET /deals/{id}/check\` — JSON той же карточки, что \`/check uuid\` в чате Payfast.

## 8. Статистика клиента

Payfast в споре пишет \`/check uuid\`. Мы отвечаем той же карточкой, что по нашей заявке: оплаченные сделки, конверсия, объём. Цифры берём из вашей сводки. Без неё клиент выглядит новым.

1. \`fingerprint\` — стабильный id покупателя у вас.
2. Соберите числа по своим оплаченным и отменённым заказам этого id.
3. Лучше сразу в \`POST /deals\` полем \`client_stat\`. Иначе сразу после \`201\` — \`POST /deals/{id}/client-stat\`.
4. Повтор можно: побеждает последняя сводка. Имеет смысл после своих PAID/CANCEL, не на каждый poll.
5. Без открытой сделки: \`POST /clients/stat\` + \`fingerprint\`.
6. Проверка: \`GET /deals/{id}/check\`.

${mdTable(
    ["Поле", "Смысл"],
    EXCHANGER_HMAC_CLIENT_STAT_FIELDS.map((f) => [`\`${f.name}\``, f.desc]),
  )}

Не присылайте ФИО, телефон, Telegram, email, карту — отбросим.

\`\`\`json
${EXCHANGER_HMAC_CLIENT_STAT_BODY}
\`\`\`

Если оператор запросил видео — в GET сделки \`needs_operator_video: true\`. Покажите клиенту снять экран, PDF уже не принимаем. Если продлили окно — callback \`event=extended\` с новым \`expires_at\` (если был \`callback_url\`).

## 9. Callback

Если передали \`callback_url\`, при зачислении, отмене или продлении пришлём \`POST application/json\`. Подписи на callback нет — сверяйте \`deal_id\` и \`client_transaction_id\` у себя. Ответьте \`200\`.

\`event\`: \`credited\`, \`cancelled\` или \`extended\`.

\`\`\`json
${EXCHANGER_HMAC_CALLBACK_EXAMPLE}
\`\`\`

Актуальное состояние всегда можно взять GET \`/deals/{id}\`.

## 10. Ошибки

${mdTable(
    ["HTTP", "detail", "Почему"],
    EXCHANGER_HMAC_ERRORS.map((e) => [e.code, e.detail.replace(/\|/g, "/"), e.why]),
  )}

## 11. Памятка

- Сохраните \`deal_id\` сразу после создания.
- \`client_transaction_id\` сделайте уникальным на заказ — повтор вернёт ту же сделку.
- \`fingerprint\` — id покупателя у вас, не общий на весь магазин. Без него статистика не привяжется.
- Пришлите \`client_stat\` сразу со сделкой — иначе \`/check\` покажет нового клиента.
- Клиенту показывайте готовый \`payment_text\` (или сумму + \`bill.bank\` / \`bill.reciver\` / \`bill.fio\`). Не выводите bill целиком: служебные поля Payfast туда не входят.
- Чек только публичным URL, не dataURI.
- Отмена: \`POST /deals/{id}/cancel\` с \`{}\`, пока нет чека. После чека или в другом статусе — 400.
`;
}
