# FocusPay Sticker AI — architecture (MVP, isolated)

**Status:** design + reviewable code scaffold in-repo.  
**Not wired** into production `main.py`, nginx, deploy scripts, or live DB migrations.  
**Path note:** this repository uses `site/exchange-backend/` (not `code/exchange-backend/`). Package lives at `site/exchange-backend/sticker_ai/`.

## 1. Goal

Safe MVP for **branded Telegram stickers** (FocusPay mono / cosmic style):

1. Idea text and/or reference image → N variants  
2. Prompt / mask edit of a chosen variant  
3. Version history  
4. Manual moderation (`review` → `approved` / `rejected`)  
5. Publish only after approve (Telegram sticker set upload is a **separate** approve step)  
6. Admin notification (allowlisted chat/user IDs only, redacted summary)

Separate from **Ops AI** (different permissions, queue names, storage prefixes, audit event namespace, no shared LLM system prompts).

## 2. Inspection findings (this repo only)

| Claimed path / doc | Result |
|---|---|
| `code/exchange-backend/` | **Absent** — use `site/exchange-backend/` |
| `ops_ai_knowledge/README.md` | **Not present** |
| `docs/PROJECT.md` | **Not present** |
| `docs/SECURITY_AUDIT_FULL_20260812.md` | **Not present** |
| `docs/Reviews/2026-08-11.md` | **Not present** |
| Existing stickers | `chat_stickers.py` + brand WEBP pack — **consume** Telegram sets, no AI gen |
| Ops AI | `ops_ai_*.py`, privacy in `privacy_redaction.py` / `docs/PRIVACY_AI_NEWS.md` |
| RBAC | `permissions.py` + `docs/PERMISSION_MATRIX.md` |
| Token TTL in code / `.env.example` | `ACCESS_TOKEN_EXPIRE_MINUTES=240` (4h). Finding «10080» not verified here — **do not read production `.env`**. Treat long-lived access tokens as a **global auth follow-up**, not blocked by Sticker AI scaffold. |
| `WEBHOOK_REQUIRE_ALLOWED_IPS` | **Not found** in this backend tree |
| Panel cookies | HttpOnly + `Secure` (https) + `SameSite=lax` in `panel_cookies.py` |

Do not invent missing files or claim production readiness.

## 3. Separation from Ops AI

| Concern | Ops AI | Sticker AI |
|---|---|---|
| Permissions | `ai.audit.*`, operator chat/dev tasks | `sticker.*` only |
| Queue | (ops job names if any) | `sticker_ai.generate`, `sticker_ai.edit`, `sticker_ai.publish` |
| Storage prefix | N/A / ops attachments | `sticker_ai/{tenant}/{task_id}/` |
| Audit events | `ops_ai_audit_events` | `sticker_ai_audit_events` (draft SQL) |
| LLM / image provider | Text LLM OpenRouter/OpenAI/Anthropic | **Image** provider abstraction (`Null` / `OfflineMock` / future self-hosted worker) |
| Cursor | `cursor_prompt` on dev tasks — **not auto-run** | Same policy: sandbox allowlist + explicit human approve; **no auto-apply / no deploy** |
| Telegram notify | Ops digests / task done | Allowlist `STICKER_AI_TG_ADMIN_IDS` / `STICKER_AI_TG_CHAT_IDS` only |

## 4. Status machine

```
draft → generating → draft (variants ready)
draft → editing → draft
draft → review → approved → publishing → published
              ↘ rejected → draft (optional revise)
Any generating/editing/publishing failure → draft (with error code) or quarantine
```

Canonical statuses: `draft`, `generating`, `editing`, `review`, `approved`, `rejected`, `publishing`, `published`, `quarantined`.

Illegal transitions raise `WorkflowError` (tested).

## 5. API surface (mounted; mutations gated)

Prefix: `/api/admin/sticker-ai`  
**UI:** `/x8/sticker-ai`

Flags (server-only / env — never commit secrets):

- `STICKER_AI_ENABLED` (default false) — list/get/audit
- `STICKER_AI_MUTATIONS_ENABLED` (default false) — create/generate/approve/publish
- `STICKER_AI_PROVIDER` = `null` | `offline_mock` | `http_worker`
- `STICKER_AI_WORKER_*` — secret manager only

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/health` | admin auth | `enabled`, `mutations`, `observation_reasons`, no secrets |
| GET | `/tasks` | `sticker.view_*` | **503** if disabled |
| GET | `/tasks/{id}` | view + ownership | IDOR → 404 |
| GET | `/audit` | `sticker.audit.view` | redacted |
| POST | `/tasks` | mutations + `sticker.create` | idempotency key |
| POST | `/tasks/{id}/generate` | mutations + `sticker.edit_own` | queue job statuses |
| POST | `/tasks/{id}/edit` | mutations + `sticker.edit_own` | asset must belong to task |
| POST | `/tasks/{id}/submit-review` | mutations + `sticker.submit_review` | |
| POST | `/tasks/{id}/approve` | mutations + `sticker.moderate` | required before publish |
| POST | `/tasks/{id}/reject` | mutations + `sticker.moderate` | |
| POST | `/tasks/{id}/publish` | mutations + `sticker.publish` | without approve → **409**; MVP = mock publish |

Bot workflow (future, separate bot token / service account): same state machine via callbacks; **no** finance webhooks.

## 6. Model provider research (no downloads performed)

| Option | License (verify before use) | Commercial | GPU (approx) | MVP role |
|---|---|---|---|---|
| **SDXL 1.0** + Fine-tune/LoRA | CreativeML Open RAIL++-M | Allowed with **use-based restrictions** (no illegal/harmful uses; retain restrictions on redistribution) | ~8–12 GB VRAM (base); +ControlNet/IP-Adapter more | **Primary commercial self-host candidate** |
| **FLUX.1 [schnell]** | Apache 2.0 | Permitted | ~12–24 GB (quantized lower) | Strong fallback / quality |
| **FLUX.1 [dev]** | Non-commercial license | **Not** for FocusPay production marketing without BFL commercial license | 16–24 GB+ | Labs only |
| **FLUX.1 [pro]** | API / commercial | Via BFL | N/A (hosted) | Optional paid API |
| ControlNet / IP-Adapter | Depends on checkpoint (often Apache / OpenRAIL) | Check each weight | Extra VRAM | Reference / structure |
| Inpainting | SDXL inpaint / FLUX fill tooling | Same as base | Extra | Mask edits |

**Fallback strategy (code):**

1. `NullProvider` — fail closed if no worker configured  
2. `OfflineMockProvider` — deterministic placeholder PNGs for CI/unit tests (no weights)  
3. Future `HttpWorkerProvider` — call isolated GPU worker with mTLS / internal secret from **secret manager**, never from prompts  
4. Manual PIL brand pack (`scripts/generate_brand_stickers.py`) remains non-AI fallback for shipping known assets  

**Do not** auto-download weights in CI or app startup. Operator must provision models under an allowlisted path outside the git tree.

Brand preset: monochrome F, near-black `#0a0a0a`, white accents, cosmic vignette; **negative prompts** block third-party trademarks, logos, NSFW, photoreal faces of real people, watermarks.

## 7. Security controls (MVP code)

- **RBAC/ABAC:** `sticker.*` permissions; object ownership; foreign task → 404  
- **Redaction:** reuse `privacy_redaction.redact_text` before any external call / audit  
- **Strict JSON schemas** for provider responses; size + timeout + HTTP status checks on HTTP provider stub  
- **Limits:** prompt length, image bytes, rate limit, idempotency keys, retry budget, quarantine on suspicious magic bytes  
- **Telegram notify:** server-side allowlist; payload = task id, status, actor pseudo-id, change type, UI path — no tokens/`.env`/logs  
- **Cursor sandbox:** repo path allowlist under `site/exchange-backend/sticker_ai/`, `docs/`, `focussite/frontend/public/brand-stickers/`; forbid `.env`, secrets, production DB; produce **diff proposal only**; require explicit approve; never deploy  
- **Secrets:** env var *names* only in docs; values from secret manager (rotation of root/bot tokens is a **platform** follow-up, out of this PR)  

### Related security follow-ups (not implemented here)

1. Short access TTL + refresh rotation + session revoke + audit (if prod still uses week-long JWT)  
2. Automated secret rotation (root, bot token) via secret manager  
3. CORS / CSRF review for cookie-auth panel writes  
4. Fail-closed webhook IP allowlist where applicable  

## 8. Storage & queue

- Object keys: `sticker_ai/{tenant_id}/{task_id}/v{n}/{asset}.webp`  
- Quarantine: `sticker_ai/_quarantine/{sha256}`  
- Queue names above; worker consumes only sticker queues (no Ops AI crossover)  
- In-process `InMemoryQueue` / `InMemoryStore` for unit tests; Redis/DB adapters deferred  

## 9. Audit fields

`actor_type`, `actor_id`, `tenant_id`, `task_id`, `event_type`, `prompt_hash`, `redacted_prompt_preview`, `model_id`, `params_digest`, `version_id`, `diff_summary`, `approval_id`, `result`, `timestamp`.  
No raw secrets / full PII / raw images in audit JSON.

## 10. Rollback

1. Do not mount routers → feature inert  
2. Drop draft tables if a migration was applied in a **lab** DB only: see `migrations/add_sticker_ai.sql` footer  
3. Delete storage prefix `sticker_ai/`  
4. Revoke `sticker.*` grants  
5. No impact on finance / Payfast / Ops AI if separation is preserved  

## 11. Readiness vs blockers

**Delivered:** architecture, RBAC, workflow package, provider abstraction, redaction, cursor sandbox, notify allowlist, unit tests, draft SQL.

**Also delivered (follow-up PR):** 

- `STICKER_AI_ENABLED` default **false** in `config.py` / `.env.example`
- Mounted read-only admin API: `GET /api/admin/sticker-ai/health|tasks|tasks/{id}`
- Admin UI `/x8/sticker-ai` (status + empty/list when enabled)
- When disabled, `/tasks*` → **503** `sticker_ai_disabled`; health still works
- `mutations: false` in health — generate/publish **not** exposed via HTTP yet

**Still blocked before production enablement:**

1. Explicit lab enable (`STICKER_AI_ENABLED=true`) + offline_mock or licensed GPU worker  
2. Apply `migrations/add_sticker_ai.sql` on lab DB only (not prod yet)  
3. Dedicated Telegram sticker publisher token  
4. HTTP mutation endpoints (create/generate/edit/review/publish) behind separate approve  
5. Global auth TTL / secret rotation follow-ups (out of scope)  
6. Frontend deploy when ready (`npm run build` + `deploy_all.py`) — **not done automatically**

**Rollback of this mount:** set `STICKER_AI_ENABLED=false` (default); remove `admin_sticker_ai` include from `main.py` if needed; UI page is inert when API returns disabled.
