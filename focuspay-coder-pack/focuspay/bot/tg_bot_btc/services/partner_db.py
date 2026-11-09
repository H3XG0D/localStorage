"""Запросы для партнёрского кабинета в Telegram-боте."""
import html
from datetime import date, datetime

from services.db import get_pool
from services import config_rates
from services.partner_tier import resolve_tier_settings, tier_info
from services.referral_links import telegram_deep_link, web_ref_link
from services.runtime_settings import partner_tier_global, refresh_settings


async def get_partner_by_telegram(user_id: int, username: str | None = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pa.*, pc.id AS campaign_id, pc.code AS campaign_code, pc.name AS campaign_name,
                   pc.partner_commission_percent, pc.ref_token, pc.is_active AS campaign_active,
                   pc.partner_tier_base_percent, pc.partner_tier_step_percent,
                   pc.partner_tier_every_n, pc.partner_tier_max_percent
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            WHERE pa.is_active = TRUE
              AND pc.is_active = TRUE
              AND pa.telegram_user_id = $1
            LIMIT 1
            """,
            user_id,
        )
        return row


async def get_partner_stats(campaign_id: int, promo_code: str, campaign_row: dict | None = None):
    pool = await get_pool()
    today = date.today()
    async with pool.acquire() as conn:
        if campaign_row is None:
            campaign_row = await conn.fetchrow(
                """
                SELECT partner_commission_percent, partner_tier_base_percent,
                       partner_tier_step_percent, partner_tier_every_n, partner_tier_max_percent
                FROM promo_campaigns WHERE id = $1
                """,
                campaign_id,
            )
        balance = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger WHERE campaign_id = $1",
            campaign_id,
        )
        today_accrued = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
            WHERE campaign_id = $1 AND type = 'accrual' AND created_at::date = $2
            """,
            campaign_id,
            today,
        )
        attracted = await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
            promo_code,
        )
        paid_orders = await conn.fetchval(
            """
            SELECT COUNT(o.id)::int
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = $1
            WHERE o.status IN ('PAID', 'COMPLETED')
            """,
            promo_code,
        )
    await refresh_settings()
    global_tier = partner_tier_global()
    settings = resolve_tier_settings(global_tier, dict(campaign_row or {}))
    tier = tier_info(int(attracted or 0), settings)
    return {
        "balance_rub": float(balance or 0),
        "today_accrued_rub": float(today_accrued or 0),
        "attracted_users": attracted or 0,
        "paid_orders": paid_orders or 0,
        "tier": tier,
    }


async def bind_partner_telegram_by_token(token: str, telegram_user_id: int) -> bool:
    pool = await get_pool()
    code = (token or "").strip().upper()
    if not code or len(code) < 8:
        return False
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pa.id, pa.telegram_user_id, pa.telegram_bind_expires_at
            FROM partner_accounts pa
            WHERE pa.telegram_bind_token = $1
              AND pa.is_active = TRUE
              AND (pa.telegram_bind_expires_at IS NULL OR pa.telegram_bind_expires_at > now())
            """,
            code,
        )
        if not row:
            return False
        if row["telegram_user_id"] and row["telegram_user_id"] != telegram_user_id:
            return False
        await conn.execute(
            """
            UPDATE partner_accounts
            SET telegram_user_id = $1,
                telegram_bind_token = NULL,
                telegram_bind_expires_at = NULL
            WHERE id = $2
            """,
            telegram_user_id,
            row["id"],
        )
    return True


async def get_partner_wallet(user_id: int) -> dict | None:
    """Партнёрский счёт (отдльно от клиентского баланса кешбэка/промо/реф.)."""
    row = await get_partner_by_telegram(user_id)
    if not row:
        return None
    stats = await get_partner_stats(row["campaign_id"], row["campaign_code"], dict(row))
    tier = stats.get("tier") or {}
    return {
        "campaign_code": row["campaign_code"],
        "campaign_name": row["campaign_name"] or row["campaign_code"],
        "balance_rub": float(stats["balance_rub"]),
        "effective_percent": float(tier.get("effective_percent", row["partner_commission_percent"] or 0)),
        "paid_orders": int(stats.get("paid_orders") or 0),
        "attracted_users": int(stats.get("attracted_users") or 0),
    }


def format_partner_cabinet_text(row, stats: dict) -> str:
    ref = row["ref_token"] or row["campaign_code"]
    tg_link = telegram_deep_link(ref)
    web_link = web_ref_link(ref, config_rates.PUBLIC_SITE_URL)
    site = config_rates.PUBLIC_SITE_URL.rstrip("/")
    refs = int(stats.get("attracted_users") or 0)
    tier = stats.get("tier") or {}
    eff = tier.get("effective_percent", float(row["partner_commission_percent"]))
    until = tier.get("refs_until_next_tier", 0)
    step = tier.get("step_percent", 5)
    every_n = tier.get("every_n", 5)
    max_pct = tier.get("max_percent", 20)
    tier_line = ""
    if tier.get("tier_fixed") or float(step) <= 0:
        tier_line = f"Фиксированная ставка: <b>{eff:g}%</b>\n"
    else:
        progress = ""
        if not tier.get("at_max_tier"):
            done = every_n - until if until else every_n
            progress = f"\n📈 До {tier.get('next_tier_percent', eff + step):g}%: <b>{done}/{every_n}</b> реф."
        tier_line = f"Рост: +{step:g}% за каждых {every_n} реф., макс. {max_pct:g}%{progress}\n"
    text = (
        f"📊 <b>Партнёрский кабинет</b>\n\n"
        f"💰 <b>Ваша ставка: {eff:g}%</b> с чистой прибыли сервиса\n"
        f"<i>Начисление по каждой оплаченной сделке приведённого клиента. "
        f"Не с оборота — только с прибыли сервиса.</i>\n"
        f"{tier_line}\n"
        f"Кампания: <code>{row['campaign_code']}</code>\n\n"
        f"💳 Баланс партнёра: <b>{stats['balance_rub']:,.2f} ₽</b>\n"
        f"ℹ️ Входит в общий баланс — вывод и списание через «Профиль».\n"
        f"📅 Начислено сегодня: <b>{stats['today_accrued_rub']:,.2f} ₽</b>\n"
        f"👥 Приведено: <b>{stats['attracted_users']}</b>\n"
        f"✅ Оплаченных сделок: <b>{stats['paid_orders']}</b>\n\n"
        f"💸 Вывод: «Профиль» в боте или {site}/cabinet\n\n"
        f"🔗 Telegram:\n{tg_link}\n\n"
        f"🌐 Сайт:\n{web_link}\n"
        f"\n🖥 Кабинет: {site}/partner/login"
    )
    return text


_HISTORY_LABELS = {
    "accrual": "начисление",
    "payout": "выплата",
    "adjustment": "корректировка",
    "spend": "списание",
}


def _history_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _history_sort_key(row) -> float:
    created = _history_value(row, "created_at")
    if isinstance(created, datetime):
        return created.timestamp()
    return 0.0


def merge_partner_history_rows(referral_rows, partner_rows, limit: int = 15) -> list:
    """Последние операции партнёра: старая рефералка и partner_ledger без hold."""
    picked = list(referral_rows or [])
    for row in partner_rows or []:
        if str(_history_value(row, "type") or "") == "hold":
            continue
        picked.append(row)
    picked.sort(key=_history_sort_key, reverse=True)
    return picked[:limit]


def _partner_history_note(note) -> str:
    text = str(note or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "от прибыли" in lowered or "(tier)" in lowered:
        return ""
    return text


def format_partner_history_message(rows) -> str:
    """Текст истории для партнёра. Пустая строка, если показывать нечего."""
    if not rows:
        return ""
    lines = ["📜 <b>Последние операции</b>\n"]
    for row in rows:
        created = _history_value(row, "created_at")
        when = created.strftime("%d.%m %H:%M") if isinstance(created, datetime) else "—"
        kind = str(_history_value(row, "type") or "")
        label = _HISTORY_LABELS.get(kind, kind or "операция")
        amount = float(_history_value(row, "amount_rub") or 0)
        sign = "+" if amount >= 0 else ""
        line = f"• {when} — {label}: <b>{sign}{amount:,.2f} ₽</b>"
        note = _partner_history_note(_history_value(row, "note"))
        if note:
            line += f"\n  {html.escape(note)}"
        lines.append(line)
    return "\n".join(lines)
