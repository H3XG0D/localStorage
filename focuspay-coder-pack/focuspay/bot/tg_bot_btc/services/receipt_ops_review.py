"""Проверка чека оператором перед отправкой в Payfast (1–3 сделка)."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from services.payment_snapshot import order_payment_snapshot, reki_payfast_id

logger = logging.getLogger("receipt_ops_review")

FIRST_ORDERS_RECEIPT_REVIEW_MAX_PAID = 3

OUTCOME_SUCCESS = "success"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_RETRYABLE = "retryable"
OUTCOME_REJECTED = "rejected"
OUTCOME_ERROR = "error"

# Payfast периодически отвечает «Попробуйте позже» (503), хотя PDF уже доступен по URL.
PAYIN_SET_CHECK_MAX_ATTEMPTS = 3
PAYIN_SET_CHECK_RETRY_DELAY_SEC = 12


async def needs_receipt_ops_review(user_id: int) -> bool:
    """Legacy: первые N сделок всегда на ops (без учёта риска)."""
    from services.db import get_buyer_ops_stats

    stats = await get_buyer_ops_stats(user_id)
    return int(stats.get("paid_count") or 0) < FIRST_ORDERS_RECEIPT_REVIEW_MAX_PAID


def _order_is_payin_rail(order: dict) -> bool:
    try:
        from services.payin_requisite_rail import is_payin_order

        return bool(is_payin_order(order))
    except Exception:
        return order.get("payin_requisite_id") is not None


def should_auto_forward_video_to_payfast(order: dict) -> bool:
    """Видео клиента сразу в Appeals Payfast, без кнопки «отправить мерчанту»."""
    if (order.get("direction") or "").lower() != "buy":
        return False
    if int(order.get("required_receipt_type") or 2) != 3:
        return False
    if _order_is_payin_rail(order):
        return False
    name = str(order.get("receipt_file") or "").strip()
    if name and not _is_video_receipt(name, order):
        return False
    return True


async def should_hold_receipt_for_ops(
    user_id: int,
    *,
    risk_level: str,
    order: dict | None = None,
) -> bool:
    """
    Держим на операторе только новый трафик (первые N сделок) и пейин-реквизит.
    Постоянникам чек сразу в Payfast: у них автоподтверждение, риск уходит
    карточкой «Автопропуск», без кнопки «отправить мерчанту».
    Видео по Payfast не держим — сразу в Appeals.
    """
    if order is not None and should_auto_forward_video_to_payfast(order):
        return False
    if order is not None and _order_is_payin_rail(order):
        return True
    from services.db import get_buyer_ops_stats

    stats = await get_buyer_ops_stats(user_id)
    paid_count = int(stats.get("paid_count") or 0)
    if paid_count >= FIRST_ORDERS_RECEIPT_REVIEW_MAX_PAID:
        return False
    # Новый клиент: если Payfast уже закрыл заявку — не держим чек.
    if order is not None and await _payfast_order_is_settled(order):
        logger.info(
            "skip ops receipt hold, payfast already settled order=%s",
            order.get("order_id"),
        )
        return False
    return True


def round_up_ops_notice(order: dict, *, pdf_meta: dict | None = None) -> str:
    """Payin-заявка с доплатой: оператору — сколько ждём на чеке и что уйдёт клиенту на баланс.

    Защита от «принял доплату, заплатил котировку»: сумма заявки уже
    поднята до номинала карты, кредит начислится автоматически после одобрения.
    """
    try:
        credit = round(float(order.get("overpay_credit_rub") or 0), 2)
        fiat = round(float(order.get("fiat_amount") or 0), 2)
    except (TypeError, ValueError):
        return ""
    if credit <= 0 or fiat <= 0:
        return ""
    quote = max(0.0, fiat - credit)

    def _rub(value: float) -> str:
        return f"{int(round(value)):,}".replace(",", " ")

    lines = [
        "⚠️ <b>Заявка с доплатой до номинала карты</b>",
        f"На чеке должно быть ровно <b>{_rub(fiat)} ₽</b> "
        f"(котировка {_rub(quote)} ₽ + доплата {_rub(credit)} ₽).",
        f"После одобрения клиенту автоматически уйдёт <b>{_rub(credit)} ₽ на баланс</b>.",
        f"Если на чеке {_rub(quote)} ₽ или любая другая сумма — отклоняй, иначе клиент получит и крипту, и {_rub(credit)} ₽.",
    ]
    if isinstance(pdf_meta, dict) and pdf_meta.get("amount_present") is False:
        lines.append(
            f"❗ В PDF не найдено {_rub(fiat)} — кредит на баланс автоматически <b>не начислится</b>, "
            "даже если одобришь. Сверь сумму руками."
        )
    return "\n".join(lines)


def inspect_receipt_pdf_meta(order: dict, receipt_name: str) -> dict | None:
    """Soft PDF meta для скоринга (None для видео / отсутствующего файла)."""
    from services.receipt_pdf_inspect import inspect_pdf_file

    if _is_video_receipt(receipt_name, order):
        return None
    local_path = _receipt_local_path(receipt_name)
    if not local_path.is_file():
        return None
    issued = _details_issued_at_from_order(order)
    fiat = None
    try:
        fiat = float(order.get("fiat_amount") or 0) or None
    except (TypeError, ValueError):
        fiat = None
    return inspect_pdf_file(
        local_path,
        fiat_amount=fiat,
        details_issued_at=issued,
    )


def _receipt_local_path(receipt_name: str) -> Path:
    from services.receipts_storage import receipts_dir

    return receipts_dir() / receipt_name


_VIDEO_RECEIPT_EXT = frozenset({"mp4", "mov", "avi", "webm", "mkv"})
_DOCUMENT_RECEIPT_EXT = frozenset({"pdf", "gif", "jpg", "jpeg", "png", "webp"})


async def post_miniapp_receipt_file(
    order: dict,
    *,
    bot=None,
    receipt_name: str | None = None,
) -> None:
    """Чек из миниаппки в ops-чат файлом: PDF документом, ролик только если это видео."""
    if str(order.get("order_source") or "").strip().lower() != "tg_miniapp":
        return
    name = str(receipt_name or order.get("receipt_file") or "").strip()
    order_id = str(order.get("order_id") or "").strip()
    if not name or not order_id:
        return
    from services.db import mark_ops_alert_once, ops_alert_was_sent

    kind = f"miniapp_receipt_file_{name}"
    if await ops_alert_was_sent(order_id, kind):
        return
    path = _receipt_local_path(name)
    if not path.is_file():
        logger.warning("miniapp receipt file missing order=%s path=%s", order_id, path)
        return
    video = _is_video_receipt(name, order)
    from services.merchant_order_id import resolve_merchant_display_id
    from services.order_ops_notify import _admin_chat_id, send_local_telegram_file

    chat_id = _admin_chat_id()
    if not chat_id:
        return
    caption = f"Миниаппка · {resolve_merchant_display_id(order)}"

    async def _remember_sent() -> None:
        await mark_ops_alert_once(order_id, kind)

    if bot is None:
        try:
            await asyncio.to_thread(
                send_local_telegram_file,
                int(chat_id),
                str(path),
                video=video,
                caption=caption,
            )
        except Exception as e:
            logger.warning("miniapp receipt file send failed order=%s: %s", order_id, e)
            return
        await _remember_sent()
        return
    try:
        with path.open("rb") as fh:
            if video:
                await bot.send_video(chat_id=chat_id, video=fh, caption=caption)
            else:
                await bot.send_document(chat_id=chat_id, document=fh, caption=caption)
    except Exception as e:
        logger.warning("miniapp receipt file send failed order=%s: %s", order_id, e)
        if not video:
            return
        try:
            with path.open("rb") as fh:
                await bot.send_document(chat_id=chat_id, document=fh, caption=caption)
        except Exception as fallback_error:
            logger.warning(
                "miniapp receipt document fallback failed order=%s: %s",
                order_id,
                fallback_error,
            )
            return
    await _remember_sent()


def _is_video_receipt(receipt_name: str, order: dict) -> bool:
    """PDF и картинки никогда не шлём как видео, даже если Payfast просит ролик."""
    ext = Path(str(receipt_name or "")).suffix.lstrip(".").lower()
    if ext in _VIDEO_RECEIPT_EXT:
        return True
    if ext in _DOCUMENT_RECEIPT_EXT:
        return False
    try:
        return int(order.get("required_receipt_type") or 2) == 3
    except (TypeError, ValueError):
        return False


def _parse_snap(order: dict) -> dict:
    return order_payment_snapshot(order)


async def _build_receipt_risk_note(
    order: dict,
    *,
    pdf_meta: dict | None,
) -> tuple[str, str]:
    """Returns (note_html, risk_level)."""
    from services.buyer_access_guards import (
        REASON_IP_REUSE,
        REASON_WALLET_REUSE,
        is_suspicious_account,
    )
    from services.buyer_risk import (
        compute_buyer_risk_score,
        format_risk_block,
    )
    from services.db import (
        count_fingerprint_users,
        find_fingerprint_reuse,
        find_ip_reuse,
        find_receipt_sha256_reuse,
        find_wallet_reuse,
        get_bot_user,
        get_buyer_ops_stats,
        get_latest_device_signal_for_order,
        get_receipt_payment_window_start_at,
        get_receipt_submitted_at,
        is_popular_fingerprint,
        merge_order_payment_snapshot,
        serialize_reuse_matches,
    )
    from services.tg_account_age import estimate_age_days
    from services.user_referral_attribution import get_attribution_details

    uid = int(order.get("user_id") or 0)
    stats = await get_buyer_ops_stats(uid) if uid else {}
    paid_count = int(stats.get("paid_count") or 0)
    bot_user = await get_bot_user(uid) if uid else None

    wallet = (order.get("wallet_address") or order.get("requisites") or "").strip()
    reuse_rows: list[dict] = []
    if wallet and uid:
        try:
            reuse_rows = await find_wallet_reuse(wallet, uid)
        except Exception as e:
            logger.debug("wallet reuse for risk: %s", e)

    account_age_days = estimate_age_days(uid) if uid else None

    snap = _parse_snap(order)
    device_sig = None
    try:
        device_sig = await get_latest_device_signal_for_order(
            str(order.get("order_id") or "")
        )
    except Exception as e:
        logger.debug("device signal for risk: %s", e)

    # Mini App IP приоритетнее orders.client_ip (часто Cloudflare/IPv6 и другой адрес)
    client_ip = None
    if device_sig and device_sig.get("ip"):
        client_ip = str(device_sig.get("ip")).strip() or None
    if not client_ip:
        raw_ip = order.get("client_ip")
        if raw_ip is not None:
            client_ip = str(raw_ip).strip() or None
            # inet может прийти как 1.2.3.4/32
            if client_ip and "/" in client_ip:
                client_ip = client_ip.split("/", 1)[0]

    ip_rows: list[dict] = []
    if client_ip and uid:
        try:
            ip_rows = await find_ip_reuse(client_ip, uid)
        except Exception as e:
            logger.debug("ip reuse for risk: %s", e)
    if not ip_rows and isinstance(snap.get("device_ip_matches"), list):
        ip_rows = list(snap.get("device_ip_matches") or [])

    # FP: добрать совпадения и пометить «когорту модели» (общий FP iPhone в TG).
    fp_rows: list[dict] = []
    if isinstance(snap.get("device_fp_matches"), list) and snap.get("device_fp_matches"):
        fp_rows = list(snap.get("device_fp_matches") or [])
    fp_raw = None
    if device_sig and device_sig.get("fingerprint"):
        fp_raw = str(device_sig.get("fingerprint") or "").strip().lower() or None
    if fp_raw and uid and not fp_rows:
        try:
            fp_rows = await find_fingerprint_reuse(fp_raw, uid)
        except Exception as e:
            logger.debug("fp reuse for risk: %s", e)
    fp_user_count = int(snap.get("device_fp_user_count") or 0)
    if fp_raw and not fp_user_count:
        try:
            fp_user_count = await count_fingerprint_users(fp_raw)
        except Exception:
            fp_user_count = len({r.get("user_id") for r in fp_rows if r.get("user_id")}) + 1
    fp_common = bool(snap.get("device_fp_common"))
    if fp_rows and not fp_common:
        fp_common = is_popular_fingerprint(fp_user_count or (len(fp_rows) + 1))
    if fp_rows:
        snap["device_fp_reuse"] = True
        snap["device_fp_matches"] = serialize_reuse_matches(fp_rows)
        snap["device_fp_common"] = fp_common
        snap["device_fp_user_count"] = fp_user_count or (len(fp_rows) + 1)

    # для карточки чека показываем reuse даже если paid_count>0
    reasons = is_suspicious_account(
        bot_user,
        0,
        has_avatar=None,
        first_name=(bot_user.get("first_name") if bot_user else None),
        wallet_reuse=bool(reuse_rows),
        account_age_days=account_age_days,
        ip_reuse=bool(ip_rows) or bool(snap.get("device_ip_reuse")),
    )
    if paid_count > 0:
        # убрать профильные (они для unpaid), оставить reuse/ip
        keep = []
        if reuse_rows:
            keep.append(REASON_WALLET_REUSE)
        if ip_rows or snap.get("device_ip_reuse"):
            keep.append(REASON_IP_REUSE)
        reasons = keep

    amount_currency = snap.get("amount_currency")
    pdf_flags = list((pdf_meta or {}).get("flags") or [])
    hash_hits: list[dict] = []
    if pdf_meta and pdf_meta.get("sha256"):
        try:
            hash_hits = await find_receipt_sha256_reuse(
                str(pdf_meta["sha256"]),
                exclude_order_id=str(order.get("order_id") or "") or None,
            )
        except Exception as e:
            logger.debug("sha256 reuse: %s", e)
        if hash_hits:
            pdf_flags = list(pdf_flags) + ["pdf_hash_reuse"]

    upload_sec = None
    # Риск «быстрый чек» — от открытия реквизитов (живая оплата), не от «Я оплатил»
    req_at = get_receipt_payment_window_start_at(order)
    sub_at = get_receipt_submitted_at(order) or datetime.now(tz=timezone.utc)
    if req_at is not None:
        try:
            if getattr(sub_at, "tzinfo", None) is None:
                sub_at = sub_at.replace(tzinfo=timezone.utc)
            upload_sec = max(0, int((sub_at - req_at).total_seconds()))
        except Exception:
            upload_sec = None

    attr = {"has": False, "label": "нет"}
    if uid:
        try:
            attr = await get_attribution_details(uid)
        except Exception:
            attr = {"has": None, "label": "?"}
    has_ref = attr.get("has")
    referral_label = str(attr.get("label") or "").strip() or None

    score, level, lines, breakdown = compute_buyer_risk_score(
        reasons=reasons,
        has_referral=has_ref,
        referral_label=referral_label,
        amount_currency=amount_currency,
        fiat_amount=float(order.get("fiat_amount") or 0),
        pdf_flags=pdf_flags,
        pdf_upload_sec=upload_sec,
        paid_count=paid_count,
        account_age_days=account_age_days,
        ip_reuse=bool(ip_rows) or bool(snap.get("device_ip_reuse")),
        fingerprint_reuse=bool(snap.get("device_fp_reuse")) and not bool(snap.get("device_fp_common")),
        fingerprint_common=bool(snap.get("device_fp_common")),
    )

    from services.order_ops_notify import format_reuse_who_html, operator_client_url, operator_url

    extra: list[str] = []
    if reuse_rows:
        bits = []
        for r in reuse_rows[:5]:
            uname = (r.get("username") or "").strip().lstrip("@")
            label = f"@{html.escape(uname)}" if uname else f"id {r.get('user_id')}"
            uid_r = r.get("user_id")
            if uid_r is not None:
                url = operator_client_url(uid_r)
                bits.append(
                    f'<a href="{html.escape(url)}">{label}</a>'
                    f" ({html.escape(str(r.get('order_id') or ''))}"
                    f" {html.escape(str(r.get('status') or ''))})"
                )
            else:
                bits.append(
                    f"{label} ({html.escape(str(r.get('order_id') or ''))}"
                    f" {html.escape(str(r.get('status') or ''))})"
                )
        extra.append("• Кошелёк уже у: " + ", ".join(bits))
    if ip_rows:
        who = format_reuse_who_html(ip_rows)
        if who:
            extra.append(f"• IP совпал с: {who}")
    if snap.get("device_fp_reuse") or snap.get("device_fp_common"):
        fp_matches = snap.get("device_fp_matches") or []
        who = format_reuse_who_html(fp_matches) if fp_matches else ""
        if snap.get("device_fp_common"):
            n = snap.get("device_fp_user_count") or snap.get("device_reuse_count") or "?"
            extra.append(
                f"• Общий FP модели ({n} акк.) — типично для одинаковых iPhone в Telegram"
                + (f": {who}" if who else "")
            )
        else:
            extra.append(
                "• Устройство (fingerprint) уже встречалось у другого аккаунта"
                + (f": {who}" if who else "")
                + (
                    f" (совпадений: {snap.get('device_reuse_count')})"
                    if snap.get("device_reuse_count") and not who
                    else ""
                )
            )
    else:
        # даже без reuse — показать что FP/IP с Mini App есть
        if device_sig and (device_sig.get("fingerprint") or device_sig.get("ip")):
            fp = (device_sig.get("fingerprint") or "")[:12]
            extra.append(
                f"• Mini App: {html.escape(str(device_sig.get('platform') or '—'))}"
                f" · IP {html.escape(str(device_sig.get('ip') or '—'))}"
                f" · FP {html.escape(fp)}…"
            )
    if hash_hits:
        h = hash_hits[0]
        uname = (h.get("username") or "").strip().lstrip("@")
        label = f"@{html.escape(uname)}" if uname else f"id {h.get('user_id')}"
        uid_h = h.get("user_id")
        if uid_h is not None:
            url = operator_client_url(uid_h)
            label = f'<a href="{html.escape(url)}">{label}</a>'
        extra.append(
            f"• Тот же файл чека уже был у {label}"
            f" / заказ {html.escape(str(h.get('order_id') or ''))}"
        )

    oid = str(order.get("order_id") or "")
    if oid:
        patch: dict[str, Any] = {}
        if breakdown:
            patch["risk_breakdown"] = breakdown
        if ip_rows:
            patch["device_ip_reuse"] = True
            patch["device_ip_matches"] = serialize_reuse_matches(ip_rows)
            patch["device_reuse_count"] = max(
                int(snap.get("device_reuse_count") or 0),
                len({r.get("user_id") for r in ip_rows if r.get("user_id") is not None}),
            )
        if fp_rows:
            patch["device_fp_reuse"] = True
            patch["device_fp_matches"] = serialize_reuse_matches(fp_rows)
            patch["device_fp_common"] = fp_common
            patch["device_fp_user_count"] = fp_user_count or (len(fp_rows) + 1)
            patch["device_reuse_count"] = max(
                int(patch.get("device_reuse_count") or snap.get("device_reuse_count") or 0),
                len({r.get("user_id") for r in fp_rows if r.get("user_id") is not None}),
            )
        if referral_label:
            patch["attribution_label"] = referral_label
            if attr.get("kind"):
                patch["attribution_kind"] = attr.get("kind")
            if attr.get("promo_code"):
                patch["attribution_promo_code"] = attr.get("promo_code")
            if attr.get("referrer_user_id") is not None:
                patch["attribution_referrer_user_id"] = attr.get("referrer_user_id")
        if patch:
            try:
                await merge_order_payment_snapshot(oid, patch)
                snap.update(patch)
                order["payment_snapshot"] = snap
            except Exception as e:
                logger.debug("risk snapshot patch: %s", e)

    block = format_risk_block(
        score=score, level=level, lines=lines, extra_lines=extra or None
    )
    return block, level


def _details_issued_at_from_order(order: dict) -> datetime | None:
    snap = _parse_snap(order)
    raw = snap.get("requisites_issued_at")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    created = order.get("created_at")
    if isinstance(created, datetime):
        if created.tzinfo is None:
            return created.replace(tzinfo=timezone.utc)
        return created.astimezone(timezone.utc)
    return None


_MSG_VIDEO_OK = (
    "✅ Видео принято. Ожидайте проверки — мы сообщим, "
    "когда оплата будет подтверждена."
)
_MSG_VIDEO_FAIL = (
    "❌ Видео НЕ доставлено платёжной системе. "
    "Попробуйте пожалуйста через 30 секунд снова."
)
_MSG_HOLD_PDF = (
    "✅ Чек принят. Ожидайте проверки — мы сообщим, "
    "когда оплата будет подтверждена."
)
_MSG_SENT_PDF = (
    "✅ Чек отправлен на проверку.\n"
    "Когда мерчант подтвердит оплату — придёт уведомление, после этого отправим крипту."
)
_MSG_DEFER_VIDEO = (
    "✅ Видео отправлено. Всё хорошо, ожидайте проверки — "
    "мы сообщим, когда оплата будет подтверждена."
)
_MSG_DEFER_PDF = (
    "✅ Чек отправлен. Всё хорошо, ожидайте проверки — "
    "мы сообщим, когда оплата будет подтверждена."
)
_MSG_TEMP = (
    "❌ Временная ошибка на стороне платёжной системы. Попробуйте отправить чек позже."
)


async def relay_reki_receipt(order: dict, receipt_name: str) -> bool:
    """PDF или видео в чат реки: текст с UUID, затем файл."""
    payfast_id = reki_payfast_id(order)
    if not payfast_id:
        return False
    from services.reki_request import send_receipt_to_reki

    path = _receipt_local_path(receipt_name)
    return await send_receipt_to_reki(
        payfast_id,
        str(path),
        video=_is_video_receipt(receipt_name, order),
    )


async def _finish_reki_relay(
    order: dict,
    *,
    bot=None,
    username: str | None,
    req_type: int,
) -> dict[str, Any]:
    from services.db import update_order_status

    order_id = str(order.get("order_id") or "")
    try:
        await update_order_status(order_id, "PENDING")
    except Exception:
        logger.warning("reki relay status update failed order=%s", order_id, exc_info=True)
    try:
        from services.order_ops_notify import notify_ops_order

        await notify_ops_order(
            "receipt_attached",
            dict(order),
            bot=bot,
            username=username,
            note="Чек ушёл в реки по ID Payfast",
        )
    except Exception:
        logger.warning("reki relay ops notify failed order=%s", order_id, exc_info=True)
    message = _MSG_VIDEO_OK if req_type == 3 else _MSG_SENT_PDF
    return _route_payload("reki_sent", "PENDING", message)


def _route_payload(
    route: str,
    status: str,
    message: str,
    *,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    return {
        "route": route,
        "status": status,
        "client_message": message,
        "parse_mode": parse_mode,
    }


async def route_client_receipt(
    order: dict,
    receipt_name: str,
    *,
    bot=None,
    username: str | None = None,
    telegram_file_id: str | None = None,
    as_document: bool = False,
) -> dict[str, Any]:
    """То же дерево, что загрузка чека в боте: удержание, Payfast, Appeals, повтор."""
    from datetime import timedelta

    from services.db import extend_order_expires_at, merge_order_payment_snapshot

    order = dict(order)
    if receipt_name:
        order["receipt_file"] = receipt_name
    order_id = str(order.get("order_id") or "")
    req_type = int(order.get("required_receipt_type") or 2)
    user_id = int(order.get("user_id") or 0)
    try:
        await merge_order_payment_snapshot(
            order_id,
            {"receipt_ops_submitted_at": datetime.now(tz=timezone.utc).isoformat()},
        )
        # Локальное окно, не dateEnd Payfast: экспайрер не снимет чек, пока его везут.
        await extend_order_expires_at(
            order_id,
            datetime.now(tz=timezone.utc) + timedelta(minutes=30),
        )
    except Exception as e:
        logger.warning("receipt prep failed order=%s: %s", order_id, e)

    pdf_meta = inspect_receipt_pdf_meta(order, receipt_name)
    risk_note, risk_level = await _build_receipt_risk_note(order, pdf_meta=pdf_meta)
    hold = await should_hold_receipt_for_ops(
        user_id, risk_level=risk_level, order=order
    )
    if _order_is_payin_rail(order):
        hold = True
    if pdf_meta:
        try:
            patch: dict[str, Any] = {
                "receipt_pdf_meta": {
                    k: pdf_meta.get(k)
                    for k in (
                        "producer",
                        "creator",
                        "creation_date",
                        "creation_date_iso",
                        "page_kind",
                        "size",
                        "flags",
                        "amount_present",
                    )
                }
            }
            if pdf_meta.get("sha256"):
                patch["receipt_sha256"] = pdf_meta["sha256"]
            await merge_order_payment_snapshot(order_id, patch)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)

    if reki_payfast_id(order):
        sent = await relay_reki_receipt(order, receipt_name)
        if not sent:
            logger.warning("reki relay failed order=%s file=%s", order_id, receipt_name)
            return _route_payload("reki_failed", "AWAITING_CHECK", _MSG_TEMP)
        return await _finish_reki_relay(
            order, bot=bot, username=username, req_type=req_type
        )

    if should_auto_forward_video_to_payfast(order):
        local = None if telegram_file_id else str(_receipt_local_path(receipt_name))
        sent = await deliver_video_to_payfast_appeals(
            order,
            bot=bot,
            file_id=telegram_file_id or "",
            local_path=local,
            as_document=as_document,
            username=username,
        )
        if not sent:
            return _route_payload("video_failed", "AWAITING_CHECK", _MSG_VIDEO_FAIL)
        return _route_payload("video_sent", "PENDING", _MSG_VIDEO_OK)

    if (order.get("direction") or "").lower() == "buy" and hold:
        await hold_receipt_for_ops_review(
            order,
            receipt_name,
            bot=bot,
            username=username,
            pdf_meta=pdf_meta,
            risk_note=risk_note,
            risk_level=risk_level,
        )
        message = _MSG_VIDEO_OK if req_type == 3 else _MSG_HOLD_PDF
        return _route_payload("held", "AWAITING_CHECK", message)

    try:
        outcome, status, result = await submit_receipt_to_payfast(order, receipt_name)
    except Exception:
        logger.exception("submit_receipt_to_payfast raised order=%s", order_id)
        return _route_payload("error", "AWAITING_CHECK", _MSG_TEMP)

    if outcome == OUTCOME_SUCCESS:
        from services.db import clear_ops_alert_once

        try:
            await clear_ops_alert_once(order_id, "receipt_attached_pending")
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        await finalize_receipt_payfast_success(
            order,
            bot=bot,
            username=username,
            risk_note=risk_note,
        )
        message = _MSG_VIDEO_OK if req_type == 3 else _MSG_SENT_PDF
        return _route_payload("submitted", "PENDING", message)

    if outcome in (OUTCOME_RETRYABLE, OUTCOME_TIMEOUT):
        logger.warning(
            "payin_set_check deferred order=%s user=%s req_type=%s status=%s outcome=%s result=%s",
            order_id,
            user_id,
            req_type,
            status,
            outcome,
            result,
        )
        await defer_receipt_send_to_background(
            order_id,
            receipt_name,
            req_type=req_type,
            last_outcome=outcome,
            last_status=status,
        )
        logger.info(
            "receipt deferred to background retry order=%s (ops card: not delivered)",
            order_id,
        )
        await finalize_receipt_deferred_for_ops(
            order,
            receipt_name,
            bot=bot,
            username=username,
            last_status=status,
            last_outcome=outcome,
        )
        message = _MSG_DEFER_VIDEO if req_type == 3 else _MSG_DEFER_PDF
        return _route_payload("deferred", "PENDING", message)

    if outcome == OUTCOME_REJECTED:
        from services.receipt_instructions import receipt_rejected_message
        from services.receipt_public_url import build_receipt_public_url

        logger.warning(
            "payin_set_check rejected order=%s user=%s req_type=%s url=%s body=%s",
            order_id,
            user_id,
            req_type,
            build_receipt_public_url(receipt_name),
            (result or {}).get("body") if isinstance(result, dict) else result,
        )
        return _route_payload(
            "rejected",
            "AWAITING_CHECK",
            receipt_rejected_message(req_type, merchant_rejected=True),
            parse_mode="HTML",
        )

    return _route_payload("error", "AWAITING_CHECK", _MSG_TEMP)


async def hold_receipt_for_ops_review(
    order: dict,
    receipt_name: str,
    *,
    bot,
    username: str | None = None,
    pdf_meta: dict | None = None,
    risk_note: str | None = None,
    risk_level: str | None = None,
) -> None:
    from services.buyer_risk import LEVEL_STRICT
    from services.callback_signatures import sign_receipt_review
    from services.db import get_order, merge_order_payment_snapshot
    from services.order_ops_notify import notify_ops_receipt_review

    order_id = str(order["order_id"])
    from services.db import clear_ops_alert_once, mark_ops_alert_once

    try:
        await clear_ops_alert_once(order_id, "receipt_attached_notify")
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    local_path = _receipt_local_path(receipt_name)
    if pdf_meta is None:
        pdf_meta = inspect_receipt_pdf_meta(order, receipt_name)

    snap_patch: dict[str, Any] = {
        "receipt_ops_pending": True,
        "receipt_ops_submitted_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if pdf_meta:
        snap_patch["receipt_pdf_meta"] = {
            k: pdf_meta.get(k)
            for k in (
                "producer",
                "creator",
                "creation_date",
                "creation_date_iso",
                "page_kind",
                "size",
                "flags",
                "amount_present",
            )
        }
        if pdf_meta.get("sha256"):
            snap_patch["receipt_sha256"] = pdf_meta["sha256"]

    await merge_order_payment_snapshot(order_id, snap_patch)

    refreshed = await get_order(order_id) or order
    if risk_note is None or risk_level is None:
        risk_note, risk_level = await _build_receipt_risk_note(
            dict(refreshed), pdf_meta=pdf_meta
        )
    payin = _order_is_payin_rail(order)
    if payin:
        note = risk_note + "\n\nПроверьте чек реквизитчика. В Payfast не отправлять."
        round_up = round_up_ops_notice(dict(refreshed), pdf_meta=pdf_meta)
        if round_up:
            note += "\n\n" + round_up
    else:
        note = risk_note + "\n\nПроверьте чек перед отправкой мерчанту"
    signature = sign_receipt_review(order_id)
    prefer_client = risk_level == LEVEL_STRICT
    from services.db import mark_ops_alert_once as _mark_review_once

    if not await _mark_review_once(order_id, f"receipt_ops_review_{receipt_name}"):
        logger.info(
            "receipt ops review notify dedup order=%s file=%s", order_id, receipt_name
        )
        return
    from services.order_ops_notify import miniapp_ops_note

    await notify_ops_receipt_review(
        dict(refreshed),
        bot,
        username=username,
        review_signature=signature,
        note=miniapp_ops_note(refreshed, note),
        prefer_client_review_group=prefer_client,
        payin_rail=payin,
    )

    if not local_path.is_file():
        logger.warning(
            "receipt file missing for ops review order=%s path=%s", order_id, local_path
        )
        return

    from services import config_rates
    from services.order_ops_notify import _admin_chat_id

    if prefer_client and config_rates.client_review_group_id():
        chat_id = config_rates.client_review_group_id()
    else:
        chat_id = _admin_chat_id()
    if not chat_id:
        return

    video = _is_video_receipt(receipt_name, order)
    if bot is None:
        from services.order_ops_notify import send_local_telegram_file

        try:
            await asyncio.to_thread(
                send_local_telegram_file,
                int(chat_id),
                str(local_path),
                video=video,
            )
        except Exception as e:
            logger.warning("ops receipt file send failed order=%s: %s", order_id, e)
            return
    else:
        try:
            if video:
                with open(local_path, "rb") as fh:
                    await bot.send_video(chat_id=chat_id, video=fh)
            else:
                with open(local_path, "rb") as fh:
                    await bot.send_document(chat_id=chat_id, document=fh)
        except Exception as e:
            logger.warning("ops receipt file send failed order=%s: %s", order_id, e)
            return
    if str(order.get("order_source") or "").strip().lower() == "tg_miniapp":
        from services.db import mark_ops_alert_once as _mark_miniapp_file

        await _mark_miniapp_file(order_id, f"miniapp_receipt_file_{receipt_name}")


async def deliver_video_to_payfast_appeals(
    order: dict,
    *,
    bot=None,
    file_id: str = "",
    local_path: str | None = None,
    as_document: bool = False,
    username: str | None = None,
) -> bool:
    """Сразу в группу Appeals. API payin_set_check для видео не зовём — иначе двойное подтверждение."""
    from services.order_ops_notify import notify_appeals_video

    sent = await notify_appeals_video(
        dict(order),
        bot=bot,
        file_id=file_id,
        local_path=local_path,
        as_document=as_document,
        username=username,
    )
    if not sent:
        return False
    await finalize_receipt_payfast_success(
        dict(order),
        bot=bot,
        username=username,
        risk_note="Видео сразу в Appeals Payfast · без подтверждения оператора",
    )
    return True


async def submit_receipt_to_payfast(
    order: dict,
    receipt_name: str,
    *,
    payin_set_check_fn=None,
) -> tuple[str, int, dict[str, Any] | None]:
    """Отправить чек в Payfast. Возвращает (outcome, http_status, result)."""
    from services.merchant_api_helpers import payin_set_check_for_order
    from services.receipt_public_url import build_receipt_public_url

    if payin_set_check_fn is None:
        from handlers.exchange_flow import payin_set_check

        payin_set_check_fn = payin_set_check

    file_url = build_receipt_public_url(receipt_name)
    order_id = order.get("order_id")
    last_result: dict[str, Any] | None = None
    last_status = 0

    for attempt in range(1, PAYIN_SET_CHECK_MAX_ATTEMPTS + 1):
        try:
            result = await asyncio.wait_for(
                payin_set_check_for_order(dict(order), file_url, payin_set_check_fn),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "payin_set_check timeout order=%s attempt=%s/%s",
                order_id,
                attempt,
                PAYIN_SET_CHECK_MAX_ATTEMPTS,
            )
            last_result = None
            last_status = 504
            if attempt < PAYIN_SET_CHECK_MAX_ATTEMPTS:
                await asyncio.sleep(PAYIN_SET_CHECK_RETRY_DELAY_SEC)
                continue
            return OUTCOME_TIMEOUT, last_status, last_result
        except Exception as e:
            logger.exception("payin_set_check failed order=%s: %s", order_id, e)
            return OUTCOME_ERROR, 0, {"error": str(e)}

        last_result = result
        status = int(result.get("status") or 0)
        last_status = status

        if status == 200:
            if attempt > 1:
                logger.info(
                    "payin_set_check recovered order=%s on attempt=%s",
                    order_id,
                    attempt,
                )
            return OUTCOME_SUCCESS, status, result
        if status == 400:
            from services.merchant_api_helpers import payfast_set_check_already_paid

            already = payfast_set_check_already_paid(result)
            if not already:
                already = await _payfast_order_is_settled(order)
            if already:
                tagged = dict(result or {})
                tagged["already_settled"] = True
                logger.info(
                    "payin_set_check already settled order=%s attempt=%s body=%s",
                    order_id,
                    attempt,
                    (result or {}).get("body"),
                )
                return OUTCOME_SUCCESS, status, tagged
            return OUTCOME_REJECTED, status, result

        retryable = status == 503
        timeout_like = status in (504, 0)
        if (retryable or timeout_like) and attempt < PAYIN_SET_CHECK_MAX_ATTEMPTS:
            logger.warning(
                "payin_set_check retry order=%s attempt=%s/%s status=%s body=%s",
                order_id,
                attempt,
                PAYIN_SET_CHECK_MAX_ATTEMPTS,
                status,
                (result or {}).get("body"),
            )
            await asyncio.sleep(PAYIN_SET_CHECK_RETRY_DELAY_SEC)
            continue

        if retryable:
            return OUTCOME_RETRYABLE, status, result
        if timeout_like:
            return OUTCOME_TIMEOUT, status, result
        return OUTCOME_ERROR, status, result

    return OUTCOME_ERROR, last_status, last_result


async def _payfast_order_is_settled(order: dict) -> bool:
    """Живой /get_order: трейдеры уже подтвердили оплату, даже если set_check вернул 400."""
    try:
        from services.payfast_payin_guard import verify_payfast_ready_for_payout

        ok, _reason, _resp = await verify_payfast_ready_for_payout(
            dict(order), require_uuid=True
        )
        return bool(ok)
    except Exception:
        logger.debug("payfast settled probe failed order=%s", order.get("order_id"), exc_info=True)
        return False


async def _try_reconcile_payfast_settled(order_id: str) -> None:
    try:
        from services.db import get_order
        from services.payfast_order_reconciler import reconcile_one_order

        refreshed = await get_order(order_id)
        if not refreshed:
            return
        await reconcile_one_order(dict(refreshed))
    except Exception:
        logger.exception("post-receipt reconcile failed order=%s", order_id)


RECEIPT_SEND_PENDING_MARKER = "receipt_send_pending"
RECEIPT_SEND_RETRY_INTERVAL_SEC = 120


def receipt_send_retry_due(snapshot: dict | None) -> bool:
    """Фоновая досылка ещё нужна: Payfast 503/timeout, заявка не завершена."""
    if not isinstance(snapshot, dict):
        return False
    pending = snapshot.get(RECEIPT_SEND_PENDING_MARKER)
    if not isinstance(pending, dict):
        return False
    if not pending.get("receipt_name"):
        return False
    if pending.get("done_at"):
        return False
    return True


async def defer_receipt_send_to_background(
    order_id: str,
    receipt_name: str,
    *,
    req_type: int = 2,
    last_outcome: str | None = None,
    last_status: int | None = None,
) -> None:
    """Пометить чек как «ждёт досылки»: фоновая задача повторит payin_set_check."""
    from datetime import datetime, timezone

    from services.db import merge_order_payment_snapshot

    await merge_order_payment_snapshot(
        str(order_id),
        {
            RECEIPT_SEND_PENDING_MARKER: {
                "receipt_name": str(receipt_name),
                "req_type": int(req_type or 2),
                "attempts": 0,
                "sent_to_payfast": False,
                "last_outcome": last_outcome or "deferred",
                "last_status": int(last_status or 0),
                "next_try_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        },
    )


async def finalize_receipt_deferred_for_ops(
    order: dict,
    receipt_name: str,
    *,
    bot=None,
    username: str | None = None,
    last_status: int = 0,
    last_outcome: str = "retryable",
) -> None:
    """Чек НЕ доставлен в Payfast: статус в панели + опс-карточка «чек не у фаста».

    Клиенту про это ничего не говорим — ему всегда отвечаем «чек отправлен».
    """
    from services.db import get_order, mark_ops_alert_once, update_order_status
    from services.order_ops_notify import notify_ops_order

    order_id = str(order["order_id"])
    await update_order_status(order_id, "PENDING")
    refreshed = await get_order(order_id) or order
    if not await mark_ops_alert_once(order_id, "receipt_deferred_notify"):
        logger.info("receipt deferred notify dedup order=%s", order_id)
        return
    note = (
        "⚠️ Чек НЕ отправлен (не у фаста) — Payfast "
        f"{last_status or 'недоступен'} ({last_outcome}).\n"
        f"Файл: {receipt_name}\n"
        "Фоновая досылка каждые 120с, карточка обновится при доставке."
    )
    from services.order_ops_notify import miniapp_ops_note

    await notify_ops_order(
        "receipt_ops_review",
        dict(refreshed),
        bot=bot,
        username=username,
        note=miniapp_ops_note(refreshed, note),
    )
    await post_miniapp_receipt_file(dict(refreshed), bot=bot, receipt_name=receipt_name)


async def clear_receipt_send_pending(order_id: str) -> None:
    from services.db import merge_order_payment_snapshot

    await merge_order_payment_snapshot(
        str(order_id),
        {RECEIPT_SEND_PENDING_MARKER: {}},
    )


async def retry_pending_receipt_send(order_id: str, *, bot=None) -> bool:
    """Одна попытка дослать отложенный чек. True — досылка больше не нужна."""
    from services.db import clear_receipt_ops_pending, get_order, merge_order_payment_snapshot

    order = await get_order(str(order_id))
    if not order:
        return True
    order = dict(order)
    if str(order.get("status") or "").upper() not in ("AWAITING_CHECK", "PENDING", "CREATED"):
        await clear_receipt_send_pending(str(order_id))
        return True
    snap = order_payment_snapshot(order)
    pending = snap.get(RECEIPT_SEND_PENDING_MARKER)
    if not isinstance(pending, dict) or not pending.get("receipt_name"):
        return True
    receipt_name = str(pending["receipt_name"])
    attempts = int(pending.get("attempts") or 0) + 1

    outcome, status, result = await submit_receipt_to_payfast(order, receipt_name)
    if outcome == OUTCOME_SUCCESS:
        await clear_receipt_send_pending(str(order_id))
        await clear_receipt_ops_pending(str(order_id))
        await finalize_receipt_payfast_success(order, bot=bot)
        logger.info(
            "receipt background retry delivered order=%s attempt=%s",
            order_id,
            attempts,
        )
        return True

    try:
        from datetime import datetime, timedelta, timezone

        await merge_order_payment_snapshot(
            str(order_id),
            {
                RECEIPT_SEND_PENDING_MARKER: {
                    "receipt_name": receipt_name,
                    "req_type": int(pending.get("req_type") or 2),
                    "attempts": attempts,
                    "sent_to_payfast": False,
                    "last_outcome": outcome,
                    "last_status": status,
                    "next_try_at": (
                        datetime.now(tz=timezone.utc)
                        + timedelta(seconds=RECEIPT_SEND_RETRY_INTERVAL_SEC)
                    ).isoformat(),
                }
            },
        )
    except Exception:
        logger.debug("receipt retry snapshot update failed order=%s", order_id, exc_info=True)
    logger.warning(
        "receipt background retry deferred order=%s attempt=%s outcome=%s status=%s body=%s",
        order_id,
        attempts,
        outcome,
        status,
        (result or {}).get("body") if isinstance(result, dict) else result,
    )
    return False


async def receipt_send_retry_task(
    *,
    shutdown_event=None,
    interval_sec: int = RECEIPT_SEND_RETRY_INTERVAL_SEC,
    batch_limit: int = 20,
) -> None:
    """Фоновая досылка чеков после Payfast 503/timeout без участия клиента."""
    import asyncio

    from services.db import get_orders_with_pending_receipt_send

    while True:
        if shutdown_event is not None and shutdown_event.is_set():
            break
        try:
            rows = await get_orders_with_pending_receipt_send(limit=batch_limit)
            for row in rows or []:
                try:
                    await retry_pending_receipt_send(str(row["order_id"]))
                except Exception:
                    logger.exception(
                        "receipt retry failed order=%s", row.get("order_id")
                    )
                if shutdown_event is not None and shutdown_event.is_set():
                    break
        except Exception:
            logger.exception("receipt_send_retry_task loop error")
        if shutdown_event is None:
            await asyncio.sleep(interval_sec)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_sec)
            break
        except asyncio.TimeoutError:
            pass


async def _notify_user_receipt_submitted(
    bot,
    user_id: int,
    *,
    req_type: int,
) -> None:
    from services.menu import main_menu_keyboard

    if req_type == 3:
        text = (
            "✅ Видео принято. Ожидайте проверки — мы сообщим, "
            "когда оплата будет подтверждена."
        )
    else:
        text = (
            "✅ Чек отправлен на проверку.\n"
            "Когда мерчант подтвердит оплату — придёт уведомление, "
            "после этого отправим крипту."
        )
    if bot:
        try:
            await bot.send_message(
                chat_id=int(user_id),
                text=text,
                reply_markup=await main_menu_keyboard(user_id),
            )
            return
        except Exception as e:
            logger.warning("notify user receipt submitted user=%s: %s", user_id, e)
    try:
        import requests
        from services import config_rates as cfg

        requests.post(
            f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(user_id),
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning("notify user receipt submitted fallback user=%s: %s", user_id, e)


async def finalize_receipt_payfast_success(
    order: dict,
    *,
    bot=None,
    username: str | None = None,
    notify_user: bool = False,
    risk_note: str | None = None,
) -> None:
    from services.db import clear_receipt_ops_pending, get_order, update_order_status
    from services.order_ops_notify import notify_ops_order

    order_id = str(order["order_id"])
    from services.db import mark_ops_alert_once

    if not await mark_ops_alert_once(order_id, "receipt_attached_notify"):
        logger.info("receipt attached notify dedup order=%s", order_id)
        return
    await clear_receipt_ops_pending(order_id)
    await update_order_status(order_id, "PENDING")
    refreshed = await get_order(order_id) or order
    note = "Ждём подтверждения от мерчанта"
    if risk_note:
        if "Риск: OK" in risk_note:
            note = risk_note.replace(
                "Риск: OK", "Риск: OK · Автопропуск → мерчант", 1
            )
        else:
            note = risk_note + "\n✅ Автопропуск → мерчант"
    from services.order_ops_notify import miniapp_ops_note

    await notify_ops_order(
        "receipt_attached",
        dict(refreshed),
        bot=bot,
        username=username,
        note=miniapp_ops_note(refreshed, note),
    )
    await post_miniapp_receipt_file(dict(refreshed), bot=bot)
    if notify_user and bot and order.get("user_id"):
        req_type = int(order.get("required_receipt_type") or 2)
        await _notify_user_receipt_submitted(bot, int(order["user_id"]), req_type=req_type)
    await _try_reconcile_payfast_settled(order_id)


async def approve_receipt_and_send_to_payfast(
    order_id: str,
    operator_id: int,
    *,
    bot,
    allow_resend: bool = False,
) -> tuple[bool, str | None]:
    from services.db import get_order, is_receipt_ops_pending

    order = await get_order(order_id)
    if not order:
        return False, "Заявка не найдена"
    order = dict(order)
    if str(order.get("status") or "").upper() != "AWAITING_CHECK":
        return False, "Заявка не ожидает чек"
    if not is_receipt_ops_pending(order) and not allow_resend:
        return False, "Чек уже обработан"
    receipt_name = (order.get("receipt_file") or "").strip()
    if not receipt_name:
        return False, "Файл чека не найден"

    if reki_payfast_id(order):
        sent = await relay_reki_receipt(order, receipt_name)
        if not sent:
            return False, "Не удалось отправить файл в реки. Попробуйте ещё раз."
        await _finish_reki_relay(
            order,
            bot=bot,
            username=None,
            req_type=int(order.get("required_receipt_type") or 2),
        )
        return True, None

    if should_auto_forward_video_to_payfast(order):
        await finalize_receipt_payfast_success(
            order,
            bot=bot,
            notify_user=True,
            risk_note="Видео уже в Appeals Payfast · без повторной отправки",
        )
        logger.info(
            "receipt ops approved video already at appeals order=%s by operator=%s",
            order_id,
            operator_id,
        )
        return True, None

    if _order_is_payin_rail(order):
        from services.db import clear_receipt_ops_pending, update_order_status
        from services.menu import main_menu_keyboard

        await clear_receipt_ops_pending(order_id)
        ok = await update_order_status(order_id, "COMPLETED")
        if not ok:
            return False, "Недопустимый переход статуса"
        if bot and order.get("user_id"):
            try:
                await bot.send_message(
                    chat_id=int(order["user_id"]),
                    text=(
                        f"✅ Чек по заявке <code>{html.escape(order_id)}</code> принят.\n"
                        "Отправим крипту после проверки."
                    ),
                    parse_mode="HTML",
                    reply_markup=await main_menu_keyboard(int(order["user_id"])),
                )
            except Exception as e:
                logger.warning("notify user payin receipt approved user=%s: %s", order.get("user_id"), e)
        logger.info(
            "receipt ops approved payin rail order=%s by operator=%s",
            order_id,
            operator_id,
        )
        return True, None

    outcome, _status, result = await submit_receipt_to_payfast(order, receipt_name)
    if outcome == OUTCOME_SUCCESS:
        await finalize_receipt_payfast_success(
            order,
            bot=bot,
            notify_user=True,
        )
        logger.info(
            "receipt ops approved order=%s by operator=%s already_settled=%s",
            order_id,
            operator_id,
            bool((result or {}).get("already_settled")),
        )
        return True, None
    if outcome == OUTCOME_REJECTED:
        err = None
        if result and isinstance(result.get("body"), dict):
            err = result["body"].get("error") or result["body"].get("msg")
        if err:
            return False, f"Payfast отклонил чек: {err}"
        return False, "Payfast отклонил чек — попросите клиента прислать новый"
    if result and result.get("local_error") == "missing_payfast_uuid":
        logger.error("receipt approve blocked: Payfast UUID missing order=%s", order_id)
        return False, "Не найден ID Payfast заявки — сообщите администратору"
    if outcome in (OUTCOME_TIMEOUT, OUTCOME_RETRYABLE):
        return False, "Payfast временно недоступен — попробуйте снова"
    err = (result or {}).get("body", {}).get("error") if result else None
    return False, err or "Ошибка отправки чека в Payfast"


async def reject_receipt_ban_and_cancel(
    order_id: str,
    operator_id: int,
    *,
    bot,
) -> tuple[bool, str | None]:
    from handlers.exchange_flow import cancel_order_merchant
    from services.menu import main_menu_keyboard
    from services.db import (
        ban_user,
        clear_receipt_ops_pending,
        get_order,
        is_receipt_ops_pending,
        is_user_banned,
        update_order_status,
    )
    from services.merchant_api_helpers import cancel_payin_for_order

    stage = "load_order"
    try:
        order = await get_order(order_id)
        if not order:
            return False, "Заявка не найдена"
        order = dict(order)
        status = str(order.get("status") or "").upper()
        if status in ("PAID", "COMPLETED"):
            return False, "Заявка уже оплачена — бан вручную через /ban"
        pending = is_receipt_ops_pending(order)
        if status in ("CANCELED", "EXPIRED") and not pending:
            # Повтор после падения mid-flight: добиваем бан
            user_id = order.get("user_id")
            if user_id:
                stage = "check_existing_ban"
                banned, _, _ = await is_user_banned(int(user_id))
                if not banned:
                    stage = "ban_user"
                    await ban_user(
                        int(user_id),
                        reason="Отклонён чек оператором",
                        operator_id=int(operator_id),
                        ban_type="hard",
                    )
                    return True, None
            return False, "Заявка уже закрыта"

        user_id = order.get("user_id")
        if (
            order.get("direction") == "buy"
            and not _order_is_payin_rail(order)
            and status not in (
                "OPERATOR_PENDING",
                "CANCELED",
                "EXPIRED",
                "PAID",
                "COMPLETED",
            )
        ):
            try:
                stage = "cancel_payfast_payin"
                await cancel_payin_for_order(order, cancel_order_merchant)
            except Exception as e:
                logger.warning("cancel payin on receipt reject order=%s: %s", order_id, e)

        if status not in ("CANCELED", "EXPIRED"):
            stage = "cancel_local_order"
            canceled = await update_order_status(order_id, "CANCELED")
            if not canceled:
                logger.error("receipt reject local cancel refused order=%s", order_id)
                return False, "Не удалось отменить заявку — повторите"
        stage = "clear_receipt_pending"
        await clear_receipt_ops_pending(order_id)

        if user_id:
            stage = "ban_user"
            await ban_user(
                int(user_id),
                reason="Отклонён чек оператором",
                operator_id=int(operator_id),
                ban_type="hard",
            )
            try:
                stage = "notify_user"
                await bot.send_message(
                    chat_id=int(user_id),
                    text=(
                        f"❌ Возникли проблемы с заявкой <code>{order_id}</code>.\n"
                        "Пожалуйста, свяжитесь с поддержкой @focus_operator"
                    ),
                    parse_mode="HTML",
                    reply_markup=await main_menu_keyboard(int(user_id)),
                )
            except Exception as e:
                logger.warning("notify user receipt reject user=%s: %s", user_id, e)

        logger.info(
            "receipt ops rejected+banned order=%s user=%s by operator=%s",
            order_id,
            user_id,
            operator_id,
        )
        return True, None
    except Exception:
        logger.exception("receipt reject failed stage=%s order=%s", stage, order_id)
        raise
