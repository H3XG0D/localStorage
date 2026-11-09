"""Гейты до выдачи Payfast-реквизитов: конверсия, кулдаун, подозрительный аккаунт."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

PAYMENT_WINDOW_MINUTES = 20
PAYFAST_RECOVERY_BUFFER_MINUTES = 7
UNPAID_COOLDOWN_MINUTES = 30
# backward-compatible alias
CANCEL_COOLDOWN_MINUTES = UNPAID_COOLDOWN_MINUTES
ACCOUNT_FRESH_HOURS = 24

LOW_CONVERSION_PCT = 50.0
LOW_CONVERSION_MIN_DENOM = 2

REASON_NO_USERNAME = "no_username"
REASON_FRESH_ACCOUNT = "fresh_account"
REASON_USERNAME_CHANGED = "username_changed"
REASON_NO_AVATAR = "no_avatar"
REASON_WEAK_NAME = "weak_name"
REASON_WALLET_REUSE = "wallet_reuse"
REASON_NO_PREMIUM = "no_premium"
REASON_TG_NEW = "tg_account_new"
REASON_IP_REUSE = "ip_reuse"
REASON_NO_REFERRAL = "no_referral"
REASON_ROUND_RUB = "round_rub"

REASON_LABELS = {
    REASON_NO_USERNAME: "нет @username",
    REASON_FRESH_ACCOUNT: f"аккаунт в боте &lt;{ACCOUNT_FRESH_HOURS}ч",
    REASON_USERNAME_CHANGED: "смена ника",
    REASON_NO_AVATAR: "нет аватарки",
    REASON_WEAK_NAME: "слабое/пустое имя",
    REASON_WALLET_REUSE: "кошелёк уже у другого аккаунта",
    REASON_NO_PREMIUM: "нет Telegram Premium",
    REASON_TG_NEW: "TG-аккаунт похож на новый (по id)",
    REASON_IP_REUSE: "IP уже был у другого аккаунта",
    REASON_NO_REFERRAL: "нет реферала/промо",
    REASON_ROUND_RUB: "круглая сумма в рублях",
}


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_conversion_pct(paid: int, failed: int) -> float | None:
    denom = int(paid) + int(failed)
    if denom <= 0:
        return None
    return round(100.0 * int(paid) / denom, 1)


def is_low_conversion(stats: dict[str, Any] | None) -> bool:
    """Низкий % успеха: есть история и % < 50, либо paid=0 при failed>=2."""
    if not stats:
        return False
    paid = int(stats.get("paid") or 0)
    failed = int(stats.get("failed") or 0)
    denom = paid + failed
    if denom < LOW_CONVERSION_MIN_DENOM:
        return False
    if paid == 0 and failed >= LOW_CONVERSION_MIN_DENOM:
        return True
    pct = stats.get("conversion_pct")
    if pct is None:
        pct = compute_conversion_pct(paid, failed)
    if pct is None:
        return False
    return float(pct) < LOW_CONVERSION_PCT


def format_conversion_line(stats: dict[str, Any] | None) -> str:
    """Строка конверсии / процента успеха для клиента."""
    if not stats:
        return "📊 Процент успеха: пока нет данных по заявкам с реквизитами."
    paid = int(stats.get("paid") or 0)
    failed = int(stats.get("failed") or 0)
    denom = paid + failed
    pct = stats.get("conversion_pct")
    if pct is None:
        pct = compute_conversion_pct(paid, failed)
    if denom <= 0:
        return "📊 Процент успеха: пока нет данных по заявкам с реквизитами."
    return (
        f"📊 Процент успеха: оплачено <b>{paid}</b> из <b>{denom}</b> "
        f"(<b>{pct:g}%</b>)."
    )


def format_low_conversion_warning(stats: dict[str, Any] | None) -> str | None:
    if not is_low_conversion(stats):
        return None
    return (
        "⚠️ Вы часто берёте заявки и не оплачиваете. "
        "Берите реквизиты только когда готовы платить."
    )


def format_conversion_block(stats: dict[str, Any] | None) -> str:
    """Конверсия + опциональное предупреждение."""
    lines = [format_conversion_line(stats)]
    warn = format_low_conversion_warning(stats)
    if warn:
        lines.append(warn)
    return "\n".join(lines)


def format_payment_rules_block(
    requisites_expires_at: datetime | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """Условия при выдаче реквизитов с фактическим сроком доступа."""
    current = _as_utc(now) or datetime.now(tz=timezone.utc)
    deadline = _as_utc(requisites_expires_at)
    if deadline is None:
        requisites_minutes = PAYMENT_WINDOW_MINUTES - PAYFAST_RECOVERY_BUFFER_MINUTES
    else:
        requisites_minutes = max(1, int((deadline - current).total_seconds() + 59) // 60)
    return (
        "⚠️ <b>Не оплачивайте с МТС Банка и Уралсиба</b> — такие переводы не принимаем.\n\n"
        "✅ Заявка создана — откройте реквизиты кнопкой ниже.\n"
        f"⏳ Реквизиты доступны около <b>{requisites_minutes}</b> минут.\n\n"
        "FocusPay может принять уже отправленный перевод ещё "
        f"<b>{PAYFAST_RECOVERY_BUFFER_MINUTES}</b> минут, после средства будут утеряны.\n\n"
        "❗️ Не закрывайте и не отменяйте заявку, если уже оплатили.\n"
        "После оплаты нажмите «💸 Я оплатил».\n"
        "Вернуться к реквизитам можно кнопкой «Активная заявка» в главном меню."
    )


def format_cooldown_message(remaining_sec: int, stats: dict[str, Any] | None = None) -> str:
    mins = max(1, (int(remaining_sec) + 59) // 60)
    lines = [
        "🔒 <b>Бот временно заблокирован</b>",
        "",
        "Вы открыли реквизиты и не совершили оплату.",
        f"Бот разморозится через ≈<b>{mins}</b> мин.",
        "",
        format_conversion_block(stats),
    ]
    return "\n".join(lines)


def format_cancel_followup_message(stats: dict[str, Any] | None = None) -> str:
    lines = [
        "🚫 Заявка отменена.",
        "",
        "Если вы уже открывали реквизиты и не оплатили — "
        f"доступ будет ограничен на <b>{UNPAID_COOLDOWN_MINUTES}</b> мин.",
        "",
        format_conversion_block(stats),
    ]
    return "\n".join(lines)


def format_expire_followup_message(stats: dict[str, Any] | None = None) -> str:
    lines = [
        "⏰ Время на оплату истекло.",
        "",
        "Заявка закрыта. Если реквизиты были открыты — "
        f"доступ к новым заявкам ограничен на <b>{UNPAID_COOLDOWN_MINUTES}</b> мин.",
        "",
        format_conversion_block(stats),
    ]
    return "\n".join(lines)


def format_account_review_pending_message() -> str:
    """Клиенту не говорим про проверку — как будто просто нет реквизитов."""
    return (
        "❌ Нет реквизитов на нужную сумму.\n\n"
        "Напишите оператору: @focus_operator"
    )


def format_account_review_rejected_message() -> str:
    return (
        "❌ Нет реквизитов на нужную сумму.\n\n"
        "Напишите оператору: @focus_operator"
    )


def format_soft_ban_no_requisites_message() -> str:
    """Тихий блок: клиенту не палим бан — как будто нет реквизитов."""
    return (
        "❌ Нет реквизитов на нужную сумму.\n\n"
        "Напишите оператору: @focus_operator"
    )


async def soft_ban_blocks_buy_requisites(user_id: int) -> bool:
    """True если тихий блок — BUY/реквизиты режем, sell/меню нет."""
    from services.db import is_user_banned

    banned, _, ban_type = await is_user_banned(int(user_id))
    return bool(banned) and (ban_type or "hard") == "soft"


def _weak_first_name(first_name: str | None) -> bool:
    raw = (str(first_name).strip() if first_name else "") or ""
    if not raw:
        return True
    if len(raw) <= 1:
        return True
    # только цифры / пунктуация / пробелы
    if all(not ch.isalpha() for ch in raw):
        return True
    return False


def is_suspicious_account(
    bot_user: Any,
    paid_count: int,
    *,
    has_avatar: bool | None = None,
    first_name: str | None = None,
    wallet_reuse: bool = False,
    is_premium: bool | None = None,
    account_age_days: int | None = None,
    ip_reuse: bool = False,
) -> list[str]:
    """Причины риска (список). Решение гейта — в buyer_risk.needs_account_review."""
    if int(paid_count or 0) > 0:
        # wallet_reuse на уже платившем не гоняем в account_review
        return []
    status = ""
    if bot_user is not None:
        status = str(
            bot_user.get("account_review_status")
            if hasattr(bot_user, "get")
            else getattr(bot_user, "account_review_status", None)
            or "none"
        )
    if status == "approved":
        return []

    reasons: list[str] = []
    username = None
    previous = None
    first_seen = None
    stored_first = None
    if bot_user is not None:
        if hasattr(bot_user, "get"):
            username = bot_user.get("username")
            previous = bot_user.get("previous_username")
            first_seen = bot_user.get("first_seen_at")
            stored_first = bot_user.get("first_name")
        else:
            username = getattr(bot_user, "username", None)
            previous = getattr(bot_user, "previous_username", None)
            first_seen = getattr(bot_user, "first_seen_at", None)
            stored_first = getattr(bot_user, "first_name", None)

    uname = (str(username).strip().lstrip("@") if username else "") or ""
    if not uname:
        reasons.append(REASON_NO_USERNAME)

    fs = _as_utc(first_seen)
    if fs is not None:
        age = datetime.now(tz=timezone.utc) - fs
        if age < timedelta(hours=ACCOUNT_FRESH_HOURS):
            reasons.append(REASON_FRESH_ACCOUNT)

    prev = (str(previous).strip().lstrip("@") if previous else "") or ""
    if prev and uname and prev.casefold() != uname.casefold():
        reasons.append(REASON_USERNAME_CHANGED)

    if has_avatar is False:
        reasons.append(REASON_NO_AVATAR)

    name = first_name if first_name is not None else stored_first
    if _weak_first_name(name):
        reasons.append(REASON_WEAK_NAME)

    if is_premium is False:
        reasons.append(REASON_NO_PREMIUM)

    if wallet_reuse:
        reasons.append(REASON_WALLET_REUSE)

    if account_age_days is not None and int(account_age_days) < 7:
        reasons.append(REASON_TG_NEW)

    if ip_reuse:
        reasons.append(REASON_IP_REUSE)

    return reasons


def format_account_age_hours(first_seen_at: datetime | None) -> tuple[float | None, str]:
    """(hours_ago, human label)."""
    fs = _as_utc(first_seen_at)
    if fs is None:
        return None, "неизвестно"
    hours = (datetime.now(tz=timezone.utc) - fs).total_seconds() / 3600.0
    if hours < 1:
        mins = max(1, int(hours * 60))
        return hours, f"{mins} мин назад"
    if hours < 48:
        return hours, f"{hours:.1f}ч назад".replace(".", ",")
    days = hours / 24.0
    return hours, f"{days:.1f}д назад".replace(".", ",")


def format_tg_account_age_label(account_age_days: int | None) -> str:
    if account_age_days is None:
        return "неизвестно"
    d = int(account_age_days)
    if d < 1:
        return "меньше суток (по id)"
    if d < 30:
        return f"~{d} дн (по id)"
    if d < 365:
        return f"~{d} дн / ~{d // 30} мес (по id)"
    years = d / 365.0
    return f"~{d} дн / ~{years:.1f} г (по id)".replace(".", ",")


def cancel_cooldown_remaining_sec(
    last_cancel_at: datetime | None,
    *,
    now: datetime | None = None,
    minutes: int = UNPAID_COOLDOWN_MINUTES,
) -> int | None:
    """Секунды до конца кулдауна или None если кулдауна нет."""
    last = _as_utc(last_cancel_at)
    if last is None:
        return None
    now_utc = _as_utc(now) or datetime.now(tz=timezone.utc)
    until = last + timedelta(minutes=int(minutes))
    rem = int((until - now_utc).total_seconds())
    if rem <= 0:
        return None
    return rem


async def check_cancel_cooldown(
    user_id: int,
    *,
    minutes: int = UNPAID_COOLDOWN_MINUTES,
) -> int | None:
    from services.db import get_last_payfast_unpaid_at

    last = await get_last_payfast_unpaid_at(user_id, within_minutes=int(minutes))
    return cancel_cooldown_remaining_sec(last, minutes=minutes)


def reason_labels_html(reasons: list[str]) -> str:
    labels = [REASON_LABELS.get(r, r) for r in reasons]
    return ", ".join(labels) if labels else "—"


@dataclass(frozen=True)
class PayfastDeadlines:
    merchant_expires_at: datetime
    requisites_expires_at: datetime
    merchant_deadline_from_provider: bool
    merchant_window_too_short: bool


def calculate_payfast_deadlines(
    merchant_end: datetime | None,
    *,
    now: datetime | None = None,
    payment_window_minutes: int = PAYMENT_WINDOW_MINUTES,
    recovery_buffer_minutes: int = PAYFAST_RECOVERY_BUFFER_MINUTES,
) -> PayfastDeadlines:
    """Рассчитать отдельные сроки реквизитов FocusPay и счёта PayFast."""
    now_utc = _as_utc(now) or datetime.now(tz=timezone.utc)
    provider_end = _as_utc(merchant_end)
    merchant_window_too_short = bool(
        provider_end is not None
        and provider_end <= now_utc + timedelta(minutes=int(recovery_buffer_minutes))
    )
    merchant_expires_at = provider_end or now_utc + timedelta(minutes=int(payment_window_minutes))
    requisites_expires_at = merchant_expires_at - timedelta(
        minutes=int(recovery_buffer_minutes)
    )
    return PayfastDeadlines(
        merchant_expires_at=merchant_expires_at,
        requisites_expires_at=requisites_expires_at,
        merchant_deadline_from_provider=provider_end is not None,
        merchant_window_too_short=merchant_window_too_short,
    )


def payfast_requisites_are_closed(
    requisites_expires_at: datetime | None,
    merchant_expires_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """True только в recovery-окне новой PayFast BUY-заявки."""
    requisites_end = _as_utc(requisites_expires_at)
    merchant_end = _as_utc(merchant_expires_at)
    if requisites_end is None or merchant_end is None:
        return False
    now_utc = _as_utc(now) or datetime.now(tz=timezone.utc)
    return requisites_end <= now_utc < merchant_end


def format_requisites_closed_message(remaining_sec: int) -> str:
    minutes = max(1, (max(0, int(remaining_sec)) + 59) // 60)
    return (
        "⏰ <b>Реквизиты закрыты.</b>\n\n"
        "Если вы уже сделали перевод, у вас есть ещё "
        f"≈<b>{minutes}</b> мин., чтобы написать оператору.\n"
        "Иначе деньги могут быть утеряны.\n\n"
        "Напишите оператору: @focus_operator"
    )


def clamp_payin_expires_at(
    merchant_end: datetime | None,
    *,
    now: datetime | None = None,
    window_minutes: int = PAYMENT_WINDOW_MINUTES,
) -> datetime:
    """Legacy helper: не продлевает старый срок оплаты дольше заданного окна."""
    now_utc = _as_utc(now) or datetime.now(tz=timezone.utc)
    cap = now_utc + timedelta(minutes=int(window_minutes))
    mend = _as_utc(merchant_end)
    if mend is None:
        return cap
    return min(mend, cap)
