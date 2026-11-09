"""Скоринг риска покупателя / чека для ops и гейта до реквизитов."""
from __future__ import annotations

import html
from typing import Any

from services.buyer_access_guards import (
    REASON_FRESH_ACCOUNT,
    REASON_IP_REUSE,
    REASON_NO_AVATAR,
    REASON_NO_PREMIUM,
    REASON_NO_REFERRAL,
    REASON_NO_USERNAME,
    REASON_ROUND_RUB,
    REASON_TG_NEW,
    REASON_USERNAME_CHANGED,
    REASON_WALLET_REUSE,
    REASON_WEAK_NAME,
)

LEVEL_OK = "OK"
LEVEL_WATCH = "СМОТРЕТЬ"
LEVEL_STRICT = "ДОСКОНАЛЬНО"

REASON_FP_REUSE = "fingerprint_reuse"

PROFILE_REASONS = frozenset(
    {
        REASON_NO_USERNAME,
        REASON_NO_AVATAR,
        REASON_WEAK_NAME,
        REASON_FRESH_ACCOUNT,
        REASON_USERNAME_CHANGED,
        REASON_NO_PREMIUM,
        REASON_TG_NEW,
    }
)


def needs_account_review(
    reasons: list[str],
    *,
    has_referral: bool | None = None,
    amount_currency: str | None = None,
    fiat_amount: float | None = None,
) -> bool:
    """
    Гейт до реквизитов:
    - wallet_reuse, или
    - ≥2 профильных маркера, или
    - холодный комбо: fresh (<24ч) + нет реферала + круглая сумма в ₽
      (кейс «сразу после /start на 6000»).
    """
    if REASON_WALLET_REUSE in (reasons or []):
        return True
    if sum(1 for r in (reasons or []) if r in PROFILE_REASONS) >= 2:
        return True
    if REASON_FRESH_ACCOUNT in (reasons or []):
        if has_referral is False and is_round_rub_input(amount_currency, fiat_amount):
            return True
    return False


def account_review_title(reasons: list[str]) -> str:
    rs = reasons or []
    has_wallet = REASON_WALLET_REUSE in rs
    has_any_profile = any(r in PROFILE_REASONS for r in rs)
    profile_gate = sum(1 for r in rs if r in PROFILE_REASONS) >= 2
    has_cold = (
        REASON_FRESH_ACCOUNT in rs
        and REASON_NO_REFERRAL in rs
        and REASON_ROUND_RUB in rs
    )
    if has_wallet and has_any_profile:
        return "🛡 Проверка клиента · профиль + кошелёк"
    if has_wallet:
        return "🛡 Проверка клиента · совпадение кошелька"
    if has_cold and not profile_gate:
        return "🛡 Проверка клиента · свежий + круглая сумма"
    return "🛡 Проверка клиента · профиль"


def risk_level_from_score(score: int) -> str:
    if score >= 5:
        return LEVEL_STRICT
    if score >= 2:
        return LEVEL_WATCH
    return LEVEL_OK


def compute_buyer_risk_score(
    *,
    reasons: list[str] | None = None,
    has_referral: bool | None = None,
    referral_label: str | None = None,
    amount_currency: str | None = None,
    fiat_amount: float | None = None,
    pdf_flags: list[str] | None = None,
    pdf_upload_sec: int | None = None,
    paid_count: int = 0,
    account_age_days: int | None = None,
    ip_reuse: bool = False,
    fingerprint_reuse: bool = False,
    fingerprint_common: bool = False,
) -> tuple[int, str, list[str], dict[str, int]]:
    """
    Returns (score, level, human_lines, breakdown).
    Score: выше = хуже. paid_count>=1 сильно снижает.
    """
    reasons = list(reasons or [])
    pdf_flags = list(pdf_flags or [])
    lines: list[str] = []
    score = 0
    breakdown: dict[str, int] = {}

    def _bump(key: str, pts: int, line: str | None = None) -> None:
        nonlocal score
        if pts == 0:
            return
        score += pts
        breakdown[key] = breakdown.get(key, 0) + pts
        if line:
            lines.append(line)

    if paid_count >= 1:
        _bump("paid_history", -3, f"• Аккаунт: уже было {paid_count} оплаченных сделок")
    else:
        profile_bits: list[str] = []
        if REASON_NO_USERNAME in reasons:
            _bump("no_username", 2)
            profile_bits.append("нет @username")
        if REASON_NO_AVATAR in reasons:
            _bump("no_avatar", 2)
            profile_bits.append("нет аватарки")
        if REASON_WEAK_NAME in reasons:
            _bump("weak_name", 1)
            profile_bits.append("слабое имя")
        if REASON_FRESH_ACCOUNT in reasons:
            _bump("fresh_in_bot", 2)
            profile_bits.append("свежий в боте (<24ч)")
        if REASON_USERNAME_CHANGED in reasons:
            _bump("username_changed", 1)
            profile_bits.append("менял @username")
        if REASON_NO_PREMIUM in reasons:
            _bump("no_premium", 1)
            profile_bits.append("нет TG Premium")
        if profile_bits:
            lines.append("• Аккаунт: " + ", ".join(profile_bits))
        else:
            lines.append("• Аккаунт: без красных маркеров профиля")

    # Возраст TG по user_id (независимо от paid — мягче если уже платил).
    age = account_age_days
    if age is None and REASON_TG_NEW in reasons:
        age = 0
    if age is not None:
        if int(age) < 7:
            pts = 3 if paid_count <= 0 else 1
            _bump(
                "tg_account_new_7d",
                pts,
                f"• TG-аккаунт похож на новый (~{int(age)} дн по id)",
            )
        elif int(age) < 30 and paid_count <= 0:
            _bump(
                "tg_account_new_30d",
                1,
                f"• TG-аккаунт относительно новый (~{int(age)} дн по id)",
            )

    if has_referral is False and paid_count <= 0:
        _bump("no_referral", 1, "• Реферал/промо: нет")
    elif has_referral:
        who = (referral_label or "").strip() or "да"
        _bump("has_referral", -1, f"• Реферал/промо: {who}")

    if REASON_WALLET_REUSE in reasons:
        _bump("wallet_reuse", 5)
        # детальная строка про чужие аккаунты добавляется снаружи

    if ip_reuse or REASON_IP_REUSE in reasons:
        _bump("ip_reuse", 3)
        # детали «у кого был IP» — снаружи

    if fingerprint_common:
        # Одинаковый FP у модели iPhone в TG WebView — слабый сигнал.
        _bump("fingerprint_common", 1)
    elif fingerprint_reuse or REASON_FP_REUSE in reasons:
        _bump("fingerprint_reuse", 3)

    cur = (amount_currency or "").strip().lower()
    if cur == "rub":
        fiat = float(fiat_amount or 0)
        roundish = fiat >= 500 and abs(fiat % 500) < 0.01
        if roundish:
            _bump(
                "round_rub",
                1,
                f"• Сумма введена в рублях ({fiat:,.0f} ₽, круглая) — "
                "чаще у фейков, чем «хочу X LTC»".replace(",", " "),
            )
        else:
            lines.append("• Сумма введена в рублях")
    elif cur == "crypto":
        _bump("crypto_input", -1, "• Сумма введена в крипте")

    pdf_lines, pdf_score, pdf_bd = _pdf_human_lines(pdf_flags)
    score += pdf_score
    for k, v in pdf_bd.items():
        breakdown[k] = breakdown.get(k, 0) + v
    lines.extend(pdf_lines)

    if pdf_upload_sec is not None and pdf_upload_sec >= 0:
        if pdf_upload_sec < 30 and paid_count <= 0:
            _bump(
                "fast_pdf_upload",
                2,
                f"• Чек прислали за {pdf_upload_sec} сек — слишком быстро для живой оплаты",
            )
        elif pdf_upload_sec < 30:
            _bump(
                "fast_pdf_upload",
                1,
                f"• Чек прислали за {pdf_upload_sec} сек — быстро",
            )

    level = risk_level_from_score(score)
    return score, level, lines, breakdown


def _pdf_human_lines(flags: list[str]) -> tuple[list[str], int, dict[str, int]]:
    if not flags:
        return [], 0, {}
    lines: list[str] = []
    score = 0
    bd: dict[str, int] = {}
    flagset = set(flags)

    def _bump(key: str, pts: int, line: str) -> None:
        nonlocal score
        score += pts
        bd[key] = bd.get(key, 0) + pts
        lines.append(line)

    if "pdf_hash_reuse" in flagset:
        _bump(
            "pdf_hash_reuse",
            5,
            "• Чек PDF: ⛔ тот же файл уже был у другого клиента — не принимать",
        )
    if "pdf_stale_creation" in flagset:
        _bump(
            "pdf_stale_creation",
            3,
            "• Чек PDF: дата создания файла раньше выдачи реквизитов — "
            "похоже на старый/чужой чек",
        )
    if "pdf_amount_missing" in flagset:
        _bump(
            "pdf_amount_missing",
            2,
            "• Чек PDF: сумма заявки не найдена в тексте — сверьте вручную",
        )
    if "pdf_text_unreadable" in flagset:
        lines.append(
            "• Чек PDF: текст не читается автоматически — сверьте сумму и получателя глазами"
        )
    if "pdf_watch_producer" in flagset:
        _bump(
            "pdf_watch_producer",
            2,
            "• Чек PDF: генератор необычный для наших банков — "
            "сверьте сумму, статус «Успешно», ФИО/карту получателя",
        )
    if "pdf_consumer_producer" in flagset:
        _bump(
            "pdf_consumer_producer",
            2,
            "• Чек PDF: похоже на редактор/печать, не на выгрузку из банка — "
            "сверьте сумму и получателя",
        )
    if "pdf_a4_page" in flagset and (
        "pdf_watch_producer" in flagset or "pdf_consumer_producer" in flagset
    ):
        _bump(
            "pdf_a4_combo",
            1,
            "• Чек PDF: формат как лист A4, не узкая квитанция — чаще макет/подделка",
        )
    elif "pdf_a4_page" in flagset and "pdf_hash_reuse" not in flagset:
        lines.append("• Чек PDF: страница A4 (бывает и у живых — сверьте сумму)")
    if "pdf_bankish_producer" in flagset and "pdf_hash_reuse" not in flagset:
        _bump("pdf_bankish", -1, "• Чек PDF: похож на банковский (типовая выгрузка)")
    if "pdf_chrome_skia" in flagset and "pdf_consumer_producer" not in flagset:
        lines.append(
            "• Чек PDF: из браузера/печати — бывает у живых; сверьте сумму и получателя"
        )
    if "pdf_date_skew" in flagset and "pdf_stale_creation" not in flagset:
        _bump("pdf_date_skew", 1, "• Чек PDF: дата создания файла далеко от заявки")
    if "pdf_amount_mismatch" in flagset:
        _bump(
            "pdf_amount_mismatch",
            3,
            "• Чек PDF: сумма в тексте не совпадает с заявкой",
        )

    return lines, score, bd


def format_risk_block(
    *,
    score: int,
    level: str,
    lines: list[str],
    extra_lines: list[str] | None = None,
) -> str:
    mark = "✅" if level == LEVEL_OK else "⚠️"
    parts = [f"{mark} Риск: {level}"]
    parts.extend(extra_lines or [])
    parts.extend(html.escape(str(line)) for line in lines)
    if level == LEVEL_STRICT:
        parts.append(
            "→ Не слать мерчанту без ручной уверенности. "
            "При совпадении кошелька — почти всегда reject + бан."
        )
    elif level == LEVEL_WATCH:
        parts.append("→ Сверить сумму и реквизиты получателя в чеке.")
    return "\n".join(parts)


def collect_reasons_for_gate(
    profile_reasons: list[str],
    *,
    wallet_reuse: bool,
) -> list[str]:
    out = list(profile_reasons)
    if wallet_reuse and REASON_WALLET_REUSE not in out:
        out.append(REASON_WALLET_REUSE)
    return out


def is_round_rub_input(amount_currency: str | None, fiat_amount: float | None) -> bool:
    if (amount_currency or "").strip().lower() != "rub":
        return False
    fiat = float(fiat_amount or 0)
    return fiat >= 500 and abs(fiat % 500) < 0.01
