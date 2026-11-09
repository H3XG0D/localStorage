# Privacy & retention — Ops AI audit + News subscriptions

## Scope

Secure handling of operator/admin AI traffic and targeted news delivery.
Does **not** change finance / Payfast formulas (see `docs/FROZEN.md` in brain repo).

## Ops AI privacy

### Redaction (deny-by-default)

Module: `privacy_redaction.py` + `ops_ai_privacy.py`.

Before any external LLM call and before audit write:

- Email, phones, Telegram @/ids, wallet addresses, card/passport-like numbers
- `api_key` / `secret` / `token` / Bearer / JWT / PEM
- UI CONTEXT: allowlist fields only; client/order PII replaced with pseudonyms
- Order amounts omitted unless `OPS_AI_ALLOW_ORDER_AMOUNTS=true`
- Images **off** unless `OPS_AI_ALLOW_IMAGES=true` **and** consent scope `images`
- RAG chunks run through the same redactor

Application loggers must not receive raw prompt/response. Security channel:
`security.ops_ai` / `security.ops_ai_audit`.

### Consent

- Version: `OPS_AI_CONSENT_VERSION` (default `ops-ai-privacy-v1`)
- Table: `ops_ai_consent`
- Endpoints:
  - `GET/POST/DELETE /api/operator/ai/consent` (+ `/ai/privacy`)
  - same under `/api/admin/ai/*` for admin FAB actor
- Without valid consent → `403`; only a technical `llm_denied_no_consent` audit event

### Audit storage

Table `ops_ai_audit_events`:

- Stores **redacted** request/response previews, hashes, correlation id, metadata
- **No** raw prompts, images, or secrets
- TTL: `OPS_AI_AUDIT_TTL_DAYS` (default 30); `expires_at` + `POST /api/admin/ai/audit/purge-expired`
- Erasure: `DELETE /api/admin/ai/audit/subject/{actor_type}/{actor_id}`
- Access log: `ops_ai_audit_access_log` (every list/read/delete)

### Access control

Permissions:

| Permission | Default |
|---|---|
| `ai.audit.view` | ADMIN only |
| `ai.audit.delete` | ADMIN only |

Object scope: non-admin with an explicit grant still only sees **own** `actor_id` rows (IDOR → 404).

## News

### Chat binding

`handlers/news_chat_register.py`:

- Sender must be in `TELEGRAM_ADMIN_IDS`
- Channel posts without `from_user` only if chat is already in `TELEGRAM_NEWS_CHAT_ID` / `news_chat_allowlist`
- `/news_bind` verifies `get_chat` and writes allowlist
- Logs use `pseudo_chat` / `pseudo_user` (`security.news`)

### Subscriptions

- `/news_on [categories…]` opt-in (version `news-privacy-v1`)
- `/news_off` opt-out
- `/news_prefs` show preferences
- Categories: `general`, `rates`, `promo`, `security`, `product`
- Table: `news_subscriptions`

### Targeted send

Admin-only `/news_send category|idempotency_key|HTML`:

- Recipients = opted-in ∩ category
- Idempotency key unique
- Rate limit: `NEWS_BROADCAST_RATE_PER_MIN` (default 30)
- Frequency cap: `NEWS_BROADCAST_FREQUENCY_HOURS` (default 24) per category
- DB row lock + in-process lock against parallel runs
- Delivery audit: `news_broadcast_deliveries` + `news_broadcast_audit`

## Migration

```bash
psql "$DATABASE_DSN" -f site/exchange-backend/migrations/add_ops_ai_audit_and_news.sql
```

Same file mirrored under `bot/tg_bot_btc/migrations/`.

## Config (.env examples, no secrets)

```
OPS_AI_CONSENT_VERSION=ops-ai-privacy-v1
OPS_AI_AUDIT_TTL_DAYS=30
OPS_AI_ALLOW_IMAGES=false
OPS_AI_ALLOW_UI_CLIENT_PII=false
OPS_AI_ALLOW_ORDER_AMOUNTS=false
NEWS_BROADCAST_RATE_PER_MIN=30
NEWS_BROADCAST_FREQUENCY_HOURS=24
NEWS_BROADCAST_MAX_RECIPIENTS=50000
```

## Tests

- `site/exchange-backend/tests/test_ops_ai_privacy_audit.py`
- `bot/tg_bot_btc/tests/test_news_privacy_broadcast.py`
- Existing `test_operator_external_acl.py` covers external-deal object ACL (finding #3)

## Residual risks

1. Chat message table `ops_ai_chat_messages` still stores operator-typed text for product UX; audit path is separate and redacted. Consider TTL on chat messages in a follow-up.
2. Offline LLM mode echoes a truncated question into the synthetic answer — still redacted at the call site, but keep provider=offline for labs only.
3. News HTML is sent with `parse_mode=HTML`; admins must not paste untrusted markup (XSS in Telegram clients is limited, still sanitize upstream if UI is added).
4. Encryption-at-rest for audit JSONB relies on PostgreSQL/disk encryption; app-level envelope encryption not added (no new secrets introduced).
