"""Совместимость со старым referral API казино.

Доверенные суммы комиссий больше не рассчитываются и не распределяются ботом.
Их формирует backend внутри атомарного settlement head-to-head игры.
"""
import logging
from typing import Any, Optional

import httpx

from config import FOCUSPAY_API_URL, FOCUSPAY_INTERNAL_TOKEN

logger = logging.getLogger(__name__)


async def get_referrer_chain(telegram_id: int) -> tuple[Optional[int], Optional[int]]:
    """Получить цепочку рефереров для неденежных compatibility-сценариев."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{FOCUSPAY_API_URL.rstrip('/')}/api/internal/users/{telegram_id}/referrer"
            headers = {"X-Internal-Token": FOCUSPAY_INTERNAL_TOKEN}
            response = await client.get(url, headers=headers)

            if response.status_code == 404:
                return None, None

            response.raise_for_status()
            referrer_l1 = response.json().get("referrer_id")
            if not referrer_l1:
                return None, None

            response_l2 = await client.get(
                f"{FOCUSPAY_API_URL.rstrip('/')}/api/internal/users/{referrer_l1}/referrer",
                headers=headers,
            )
            referrer_l2 = (
                response_l2.json().get("referrer_id")
                if response_l2.status_code == 200
                else None
            )
            return referrer_l1, referrer_l2
    except Exception:
        logger.exception("Failed to fetch referrer chain for %s", telegram_id)
        return None, None


async def distribute_casino_commission(
    focuspay_client=None,
    game_id: Optional[str] = None,
    winner_telegram_id: Optional[int] = None,
    total_commission: Any = None,
    casino_settings: Optional[dict] = None,
    **legacy_kwargs: Any,
) -> dict[str, Any]:
    """Сохранённая публичная функция для совместимости со старыми импортами.

    Функция намеренно не принимает решений о деньгах. Новые игры вызывают
    ``FocusPayClient.settle_head_to_head_game``; backend сам рассчитывает и
    распределяет комиссию. Старый прямой вызов завершается без побочных
    эффектов, чтобы исключить двойное начисление.
    """
    resolved_game_id = game_id or legacy_kwargs.get("idempotency_key")
    logger.warning(
        "Legacy commission distribution skipped for game %s; "
        "atomic backend settlement owns commission allocation",
        resolved_game_id,
    )
    return {
        "success": False,
        "skipped": True,
        "reason": "commission_is_managed_by_atomic_backend_settlement",
        "game_id": resolved_game_id,
    }
