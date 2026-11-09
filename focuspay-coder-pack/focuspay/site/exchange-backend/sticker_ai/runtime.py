"""Process-local Sticker AI runtime (in-memory until DB migration approved)."""
from __future__ import annotations

from functools import lru_cache

from config import settings
from sticker_ai.limits import StickerLimits
from sticker_ai.notify import NotifyAllowlist, StickerNotifier
from sticker_ai.provider import build_provider
from sticker_ai.service import StickerAiService
from sticker_ai.storage import InMemoryAssetStore


def is_enabled() -> bool:
    return bool(getattr(settings, "sticker_ai_enabled", False))


def mutations_enabled() -> bool:
    """HTTP create/generate/approve/publish — separate from read list."""
    return is_enabled() and bool(getattr(settings, "sticker_ai_mutations_enabled", False))


def require_enabled() -> None:
    """HTTP layer calls this; raises FastAPI HTTPException when flag is off."""
    if not is_enabled():
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="sticker_ai_disabled")


def require_mutations() -> None:
    require_enabled()
    if not mutations_enabled():
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="sticker_ai_mutations_disabled")


def provider_name() -> str:
    return (getattr(settings, "sticker_ai_provider", None) or "null").strip().lower()


def _lelouch_ready() -> bool:
    return bool((getattr(settings, "ops_ai_openai_api_key", "") or "").strip()) and bool(
        (getattr(settings, "ops_ai_openai_base_url", "") or "").strip()
    )


def provider_ready() -> bool:
    kind = provider_name()
    if kind in ("offline_mock", "offline", "mock"):
        return True
    if kind in ("lelouch", "openai", "openai_images"):
        return _lelouch_ready()
    if kind in ("http", "http_worker", "worker"):
        return bool((getattr(settings, "sticker_ai_worker_base_url", "") or "").strip()) and bool(
            (getattr(settings, "sticker_ai_worker_token", "") or "").strip()
        )
    return False


@lru_cache(maxsize=1)
def get_service() -> StickerAiService:
    limits = StickerLimits(rate_per_minute=int(getattr(settings, "sticker_ai_rate_per_min", 20) or 20))
    kind = provider_name()
    tenant_id = str(getattr(settings, "sticker_ai_tenant_id", None) or "focuspay")
    # Never auto-build http_worker without token; fall back to null.
    # Token stays in process memory only — never logged here.
    try:
        if kind in ("lelouch", "openai", "openai_images"):
            # Reuse Lelouch Ops AI creds — never log / never copy into sticker worker token.
            provider = build_provider(
                "lelouch",
                base_url=getattr(settings, "ops_ai_openai_base_url", "") or "",
                api_token=getattr(settings, "ops_ai_openai_api_key", "") or "",
                model=getattr(settings, "sticker_ai_image_model", None) or "gpt-image-2",
                limits=limits,
            )
        else:
            provider = build_provider(
                kind,
                base_url=getattr(settings, "sticker_ai_worker_base_url", "") or "",
                api_token=getattr(settings, "sticker_ai_worker_token", "") or "",
                limits=limits,
            )
    except Exception:
        provider = build_provider("null")
    allow = NotifyAllowlist.from_csv(
        users=getattr(settings, "sticker_ai_tg_admin_ids", "") or "",
        chats=getattr(settings, "sticker_ai_tg_chat_ids", "") or "",
    )
    return StickerAiService(
        provider=provider,
        store=InMemoryAssetStore(limits=limits, tenant_id=tenant_id),
        notifier=StickerNotifier(allowlist=allow),
        limits=limits,
        tenant_id=tenant_id,
    )


def reset_service_cache() -> None:
    """Tests only."""
    get_service.cache_clear()


def observation_reasons() -> list[str]:
    """Human-facing codes explaining why UI stays in watch mode (no secrets)."""
    reasons: list[str] = []
    if not is_enabled():
        reasons.append("flag_disabled")
    if not mutations_enabled():
        reasons.append("mutations_closed")
    if not provider_ready():
        reasons.append("provider_not_ready")
    kind = provider_name()
    if kind in ("null", "", "none"):
        reasons.append("provider_null")
    return reasons


def health_payload(*, principal: dict | None = None) -> dict:
    kind = provider_name()
    svc = None
    queue_snapshot = None
    try:
        if is_enabled():
            svc = get_service()
            queue_snapshot = svc.queue.snapshot()
    except Exception:
        queue_snapshot = None

    my_perms: list[str] = []
    if principal:
        raw = principal.get("permissions") or []
        my_perms = sorted(str(p) for p in raw if str(p).startswith("sticker."))

    return {
        "enabled": is_enabled(),
        "mutations": mutations_enabled(),
        "provider": kind,
        "provider_ready": provider_ready(),
        "image_model": str(getattr(settings, "sticker_ai_image_model", None) or "gpt-image-2"),
        "tenant_id": str(getattr(settings, "sticker_ai_tenant_id", None) or "focuspay"),
        "queues": ["sticker_ai.generate", "sticker_ai.edit", "sticker_ai.publish"],
        "queue_snapshot": queue_snapshot,
        "storage_prefix": "sticker_ai",
        "ops_ai_isolated": True,
        "observation_reasons": observation_reasons(),
        "my_permissions": my_perms,
        # Explicit: no tokens / URLs with secrets in this payload.
        "secrets_exposed": False,
    }
