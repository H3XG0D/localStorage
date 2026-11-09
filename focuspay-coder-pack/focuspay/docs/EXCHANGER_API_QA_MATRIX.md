# Exchanger HMAC API — QA matrix (staging)

Staging-only checklist for the shop HMAC API (`/api/exchanger/v1`) and our mirror surfaces
(`/exchanger`, `/ops/external`, `/x8/external`). Do not run against production.

**Environment (this run):** staging runtime `full-panel-pvp`, exchanger **940001**
(Fixture External Exchanger) — not payments `92001`. Trust / auto-credit **off**. Gateway via SSH tunnel
`http://127.0.0.1:18081`. After `staging-sync` (2026-09-11): HMAC cancel/stat/check, ops video/extend, Redis replay, callback `event_id` deployed.

**Runner:** [`focussite/scripts/staging-exchanger-hmac-smoke.py`](../focussite/scripts/staging-exchanger-hmac-smoke.py)

**Result columns:** `auto` = smoke script; `manual` = browser; `skip` = not safe/possible on this profile without invasive setup.

| ID | Scenario | Money risk | How | Expect (shop) | Expect (us) | Result |
|---|---|---|---|---|---|---|
| H1 | Staging reachable + HMAC key active | low | auto | create works | shift open | |
| H2 | Live/fake Payfast | med | auto | bill in create | synthetic OK | |
| H3 | Smoke fail-closed without env | low | auto | exit ≠ 0 | — | |
| A1 | No HMAC headers | low | auto | 401 | — | |
| A2 | Bad API key | low | auto | 401 | — | |
| A3 | Bad signature (wrong body) | low | auto | 401 Invalid signature | — | |
| A4 | Timestamp skew > 5 min | low | auto | 401 Timestamp expired | — | |
| A5 | Replay same ts+body | low | auto | 401 Replay rejected | — | |
| A6 | Uppercase hex signature | low | auto | 401 | — | |
| A7 | Wrong secret | low | auto | 401 | — | |
| A8 | Revoked key / shop disabled | low | skip | 401 | restore key after | skip — only one active key |
| A9 | GET signed with empty body | low | auto | 200 | — | |
| A10 | Body bytes ≠ signed JSON | low | auto | 401 | — | |
| B1 | create amount_rub + SBPRUB | high | auto | 201 + bill | deal in queue | |
| B2 | create amount_rub + CARDRUB | high | auto | 201 | — | |
| B3 | create amount_crypto usdt | high | auto | 201 | — | |
| B4 | no sub_token → SBPRUB | med | auto | SBPRUB | — | |
| B5 | fingerprint + callback + client_stat | med | auto | 201 | callback stored | |
| B6 | no fingerprint | med | auto | 201 | — | |
| B7 | no client_transaction_id | med | auto | 201 | — | |
| B8 | idempotent client_transaction_id | high | auto | same deal id | no 2nd payin | |
| B9 | new client_transaction_id | high | auto | new deal id | — | |
| B10 | amount ≤ 0 | low | auto | 400 | — | |
| B11 | no amount | low | auto | 400 | — | |
| B12 | rate unavailable | low | skip | 503 | need Rapira mock | skip |
| B13 | no operator on shift | med | skip | 503 | invasive | skip |
| B14 | markup on_deal client_pays | high | auto | pays = amount + markup | formula_text | |
| B15 | no internal Payfast fields leaked at top | med | auto | bill / payment_text / expires_at | — | |
| C1 | create → get → paid → receipt → pending | high | auto | pending | ops sees receipt | |
| C2 | ops confirm → confirmed + credited cb + 1 ledger | high | auto | confirmed + signed callback | ledger=1 | |
| C3 | create → cancel → cancelled (+ cb) | high | auto | cancelled | callback cancelled | |
| C4 | lookup GET id / query / POST get | low | auto | same deal | — | |
| C5 | client-stat + clients/stat + /check | low | auto | check card | — | |
| C6 | ops extend → callback extended | med | auto | expires_at later | callback extended | |
| D1 | cancel after receipt/pending | high | auto | 400 | — | |
| D2 | cancel after confirmed | high | auto | 400 | — | |
| D3 | paid twice | med | auto | 400 already / no double | — | |
| D4 | receipt not URL / not pdf-ish | med | auto | 400 | — | |
| D5 | receipt on foreign deal_id | high | auto | 404 | no leak | |
| D6 | receipt when pending/confirmed | high | auto | 400 | — | |
| D7 | payin error cancels deal | med | skip | cancelled | need merchant fail inject | skip |
| D8 | race cancel vs receipt | high | auto | one wins; no credit | — | |
| D9 | double confirm | high | auto | one ledger row | — | |
| D10 | video re-request | med | auto | awaiting_receipt + video flag | PDF blocked | |
| E1 | idempotent create no double credit | high | auto | = B8 | ledger unchanged | |
| E2 | outbound callback signed, no secret in body | high | auto | X-Signature present | no secret/api_key in JSON | |
| E3 | inbound HMAC replay | high | auto | = A5 | — | |
| E4 | trust off + internal settle → no auto credit | high | auto | not confirmed | skipped reason | |
| E5 | settle wrong ref | high | auto | no credit | deal_not_found/skip | |
| E6 | ops confirm is intentional credit path | high | auto | confirmed | documented | |
| E7 | HMAC cannot admin-immediate-credit | high | auto | no admin route | 401/404 | |
| E8 | HMAC cannot ops confirm | high | auto | 401/403 | — | |
| E9 | payout double-complete | high | skip | one debit | needs cabinet password | skip / manual |
| E10 | payout_on_credit double | high | skip | HMAC has no payout_on_credit field | cabinet only | skip |
| E11 | amount mismatch no auto-confirm | high | auto | trust off path | E4 covers | |
| E12 | client_pays locked after create | high | auto | GET same pays | — | |
| E13 | foreign deal_id | high | auto | 404 | — | |
| E14 | no secret leak in deal JSON | high | auto | no secret fields | — | |
| E15 | multi-worker replay cache | med | note | in-memory ReplayCache | known gap across workers | note |
| F1 | `/exchanger` UI | med | manual | — | deal list/statuses | |
| F2 | `/ops/external` UI | high | manual | — | confirm/cancel/video | |
| F3 | `/x8/external` UI | high | manual | — | ledger/keys | |
| F4 | exchanger chat | low | manual | — | messages | |
| F5 | balance after credit | high | manual | — | matches API | |
| G1 | cabinet JWT create/paid/receipt/cancel | high | skip | needs password | — | skip |
| G2 | cabinet payouts | high | skip | needs owner login | — | skip |

## Money-risk priority

1. Ledger credit paths: ops confirm, Payfast auto-confirm (trust on), admin immediate create.
2. Idempotent create / double confirm / cancel-after-pay races.
3. HMAC auth (replay, skew, signature).
4. Outbound callback forgery resistance (shop must verify our signature).

## How to re-run

```bash
# local tunnel
ssh -N -L 18081:127.0.0.1:18081 focuspay-test

# on staging host (preferred: callback reachable from backend)
cd /opt/focuspay/focussite
# see script docstring for docker one-liner
```

## Run log (2026-09-11)

**Host:** staging runtime `full-panel-pvp`, exchanger **940001**, tunnel `127.0.0.1:18081`.  
**Deploy:** `focussite/scripts/staging-sync.sh` + backend rebuild (cancel/stat/check, ACL null-owner, video/extend, Redis replay, callback `event_id`+retries, PDF blocked when video required).  
**Runner:** `focussite/scripts/staging-exchanger-hmac-smoke.py`  
**Counts (after deploy):** **PASS=52 FAIL=0 SKIP=13 NOTE=1** (base `confirm`/`cancel` without `*_any` grants).

### Smoke results (auto) — post-deploy

| ID | Result | Detail |
|---|---|---|
| H1–H3 | PASS | staging + HMAC + fail-closed |
| A1–A7, A9–A10 | PASS | auth/HMAC abuse |
| A8 | SKIP | only one active key |
| B1–B11, B14–B15 | PASS | create variants + markup lock |
| B8 / E1 | PASS | idempotent `client_transaction_id` |
| B12–B13 | SKIP | need Rapira/shift injection |
| C1 | PASS | create→paid→receipt→pending |
| C2 / E2 / E6 / D9 | PASS | ops confirm (base ACL) → signed credited + `event_id`, ledger=1 |
| C3 | PASS | HMAC cancel works |
| C4–C6 | PASS | lookups, client-stat/check, ops extend |
| D1–D6, D8, D10 | PASS | lifecycle rejects + video + PDF blocked |
| D7 | SKIP | merchant fail inject |
| E3–E5, E7–E8, E11–E14 | PASS | trust-off settle, wrong ref, HMAC cannot admin/ops |
| E9–E10, G* | SKIP | cabinet password / payouts |
| E15 | NOTE | ReplayCache prefers Redis SET NX; memory fallback |
| F* | SKIP in smoke | UI earlier: cabinet+admin OK; panel now includes `/ops/external` in build |

### Critical money / abuse findings (resolved vs open)

1. ~~Staging backend lag~~ — **fixed** by staging-sync (cancel/stat/check/video/extend).
2. ~~ACL HMAC null-owner needed confirm_any~~ — **fixed** in deployed ACL (base confirm/cancel); grants removed; smoke C2 PASS.
3. Harden: Redis replay + callback `event_id` + retries + delivery ring in Redis; PDF rejected when `required_receipt_type=3`.
4. Partner docs narrowed to canon in `exchangerHmacDocs.ts`; PERMISSION_MATRIX external policy clarified.

### Human poke list (remaining)

1. Browser: `/ops/external` with client-ops on shift — confirm list/actions look right.
2. Cabinet chat + one payout complete/reject (E9).
3. Real shop: verify callback signature + `event_id` dedupe.
4. Prod deploy of same SHA — only after explicit «го».
