"""Apply promo attribution from /start deep-link payload."""
from services.db import (
    assign_promo_to_user_if_first,
    get_active_promo_campaign_by_code,
    get_active_promo_campaign_by_ref_token,
)
from services.referral_links import parse_start_payload


async def apply_promo_from_start_payload(user_id: int, payload: str) -> bool:
    """
    Привязывает пользователя к кампании по ref_token или promo_<code>.
    Возвращает True, если создана новая привязка.
    """
    raw = (payload or "").strip()
    if not raw:
        return False

    ref_token = parse_start_payload(raw)
    if ref_token:
        campaign = await get_active_promo_campaign_by_ref_token(ref_token)
        if campaign and (campaign.get("campaign_kind") or "") not in ("fixed_rub", "exchange_discount"):
            return await assign_promo_to_user_if_first(user_id, campaign["code"])

    if raw.startswith("promo_"):
        code = raw[len("promo_") :].strip()
        if code:
            campaign = await get_active_promo_campaign_by_code(code)
            if campaign and (campaign.get("campaign_kind") or "") not in ("fixed_rub", "exchange_discount"):
                return await assign_promo_to_user_if_first(user_id, code)

    return False
