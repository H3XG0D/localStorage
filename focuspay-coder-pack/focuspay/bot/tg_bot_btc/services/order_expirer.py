import asyncio
import logging

from services.db import get_expired_orders, get_order, update_order_status
from services.user_cashback_db import release_orphan_balance_holds

logger = logging.getLogger("order_expirer")

CHECK_INTERVAL = 10
NOTIFY_DELAY = 0.05
EXPIRABLE_STATUSES = frozenset(
    {"CREATED", "AWAITING_CHECK", "PENDING", "OPERATOR_PENDING"}
)
NUDGE_REMAINING_SEC = 300
# Типы чека, которые клиент присылает сам: 2 — повторный PDF, 3 — видео.
CLIENT_RECEIPT_TYPES = frozenset({2, 3})


def _order_trace(order: dict) -> str:
    """Контекст заявки для логов — искать историю можно по Payfast uuid."""
    from services.db import get_merchant_expires_at
    from services.merchant_order_id import resolve_payfast_uuid_system

    merchant_end = get_merchant_expires_at(order)
    return (
        f"order={order.get('order_id')} "
        f"payfast={resolve_payfast_uuid_system(order) or '-'} "
        f"status={order.get('status')} "
        f"req_type={order.get('required_receipt_type') or 0} "
        f"expires_at={order.get('expires_at')} "
        f"merchant_end={merchant_end.isoformat() if merchant_end else '-'}"
    )


def _receipt_wait_deadline(order: dict):
    """Докуда ждём повторный чек/видео от клиента, или None если ждать нечего.

    Только для повторного запроса (Payfast отклонил PDF, appeals попросил видео).
    Первичное ожидание чека после «Я оплатил» истекает по таймеру оплаты, как и раньше.
    """
    from datetime import timedelta

    from services import config_rates
    from services.db import get_receipt_recheck_requested_at

    if str(order.get("status") or "").upper() != "AWAITING_CHECK":
        return None
    if int(order.get("required_receipt_type") or 0) not in CLIENT_RECEIPT_TYPES:
        return None
    requested_at = get_receipt_recheck_requested_at(order)
    if requested_at is None:
        return None
    window = max(0, int(getattr(config_rates, "RECEIPT_WAIT_WINDOW_MINUTES", 0) or 0))
    return requested_at + timedelta(minutes=window)


async def _notify_ops_receipt_wait_expired(order: dict, bot) -> None:
    from services.db import mark_ops_alert_once
    from services.order_ops_notify import notify_ops_order

    order_id = str(order["order_id"])
    if not await mark_ops_alert_once(order_id, "receipt_wait_expired"):
        return
    req_type = int(order.get("required_receipt_type") or 0)
    what = "видео" if req_type == 3 else "чек"
    try:
        await notify_ops_order(
            "expired",
            dict(order),
            bot=bot,
            note=(
                f"⌛️ Клиент так и не прислал {what} — заявка истекла по таймауту "
                f"ожидания. Проверьте вручную, если оплата всё же прошла."
            ),
        )
    except Exception as e:
        logger.warning("ops notify receipt-wait expire failed order=%s: %s", order_id, e)


async def _send_payment_nudges(bot) -> None:
    from datetime import datetime, timezone

    from services.buy_payment_prompt import build_requisites_webapp_markup, webapp_requisites_enabled
    from services.buyer_access_guards import format_requisites_closed_message
    from services.db import (
        acquire_order_payment_snapshot_lease,
        complete_order_payment_snapshot_lease,
        get_merchant_expires_at,
        get_orders_needing_payment_nudge,
        get_orders_with_closed_payfast_requisites,
        merge_order_payment_snapshot,
        release_order_payment_snapshot_lease,
    )
    from services.merchant_order_id import resolve_merchant_display_id

    recovery_rows = await get_orders_with_closed_payfast_requisites(limit=40)
    marker = "payment_requisites_closed_7m_sent_at"
    for row in recovery_rows:
        order_id = str(row["order_id"])
        uid = int(row["user_id"])
        lease_id = None
        try:
            lease_id = await acquire_order_payment_snapshot_lease(order_id, marker)
            if not lease_id:
                continue
            merchant_expires_at = get_merchant_expires_at(dict(row))
            if merchant_expires_at is None:
                raise ValueError("merchant_expires_at missing or unparseable")
            remaining_sec = max(
                0,
                int((merchant_expires_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()),
            )
            display_id = resolve_merchant_display_id(dict(row))
            text = (
                f"Заявка <code>{display_id}</code>\n\n"
                + format_requisites_closed_message(remaining_sec)
            )
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            if not await complete_order_payment_snapshot_lease(order_id, marker, lease_id):
                logger.warning("PayFast requisites-close notice completion lost order=%s", order_id)
            await asyncio.sleep(NOTIFY_DELAY)
        except Exception as e:
            if lease_id:
                try:
                    await release_order_payment_snapshot_lease(order_id, marker, lease_id)
                except Exception:
                    logger.warning(
                        "PayFast requisites-close notice lease release failed order=%s",
                        order_id,
                        exc_info=True,
                    )
            logger.warning("PayFast requisites-close notice failed order=%s: %s", order_id, e)

    rows = await get_orders_needing_payment_nudge(remaining_sec=NUDGE_REMAINING_SEC, limit=40)
    for row in rows:
        order_id = str(row["order_id"])
        uid = int(row["user_id"])
        try:
            await merge_order_payment_snapshot(
                order_id,
                {
                    "payment_nudge_5m_sent_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            )
            display_id = resolve_merchant_display_id(dict(row))
            fiat = float(row["fiat_amount"] or 0)
            text = (
                "⏰ <b>На оплату осталось ≈5 минут</b>\n\n"
                f"Заявка <code>{display_id}</code> скоро закроется.\n"
                f"Сумма: <b>{fiat:,.0f}</b> ₽\n\n".replace(",", " ")
                + "Откройте реквизиты и завершите перевод, затем нажмите «💸 Я оплатил»."
            )
            kwargs = {"chat_id": uid, "text": text, "parse_mode": "HTML"}
            if webapp_requisites_enabled():
                kwargs["reply_markup"] = build_requisites_webapp_markup(order_id)
            await bot.send_message(**kwargs)
            await asyncio.sleep(NOTIFY_DELAY)
        except Exception as e:
            logger.warning("payment nudge failed order=%s: %s", order_id, e)


async def expire_orders_task(bot, *, shutdown_event: asyncio.Event | None = None):
    from handlers.exchange_flow import cancel_order_merchant

    while True:
        if shutdown_event and shutdown_event.is_set():
            break
        try:
            await _send_payment_nudges(bot)
        except Exception as e:
            logger.warning("payment nudge pass failed: %s", e)

        try:
            orphan_ids = await release_orphan_balance_holds()
            if orphan_ids:
                logger.warning("released orphan balance holds: %s", orphan_ids)
        except Exception as e:
            logger.warning("orphan balance hold sweep failed: %s", e)

        try:
            from services.stale_payin_hold import sweep_superseded_completed_payins

            closed = await sweep_superseded_completed_payins(bot=bot)
            if closed:
                logger.info("superseded completed payins: %s", closed)
        except Exception as e:
            logger.warning("superseded completed sweep failed: %s", e)

        try:
            expired = await get_expired_orders(limit=100)
            for row in expired:
                if shutdown_event and shutdown_event.is_set():
                    break

                order_id = row["order_id"]
                order = await get_order(order_id)
                if not order or order["status"] not in EXPIRABLE_STATUSES:
                    continue

                # Чек на проверке у оператора: свежий hold не трогаем.
                # Потолок нужен — иначе заявка жила неделями и блокировала обмен.
                from services.db import (
                    find_matching_paid_buy_payout,
                    is_receipt_ops_pending,
                )
                from services.stale_payin_hold import (
                    ACTION_COMPLETE,
                    ACTION_HOLD_OPS,
                    ACTION_HOLD_PF,
                    ACTION_SKIP_SETTLED,
                    ACTION_SUPERSEDE,
                    close_superseded_payin,
                    complete_stale_ops_pending_if_settled,
                    decide_stale_payin_action,
                    is_video_hold,
                    receipt_ops_pending_is_fresh,
                )

                ops_pending = is_receipt_ops_pending(dict(order))
                sibling = None
                sibling_lookup_failed = False
                if (order.get("direction") or "").lower() == "buy":
                    try:
                        sibling = await find_matching_paid_buy_payout(dict(order))
                    except Exception as e:
                        sibling_lookup_failed = True
                        logger.warning(
                            "sibling paid lookup failed order=%s: %s",
                            order_id,
                            e,
                        )

                pf_ok = None
                pf_err = None
                resp = None
                need_pf = (
                    (order.get("direction") or "").lower() == "buy"
                    and order["status"] in ("AWAITING_CHECK", "PENDING")
                    and (
                        sibling
                        or not ops_pending
                        or not receipt_ops_pending_is_fresh(dict(order))
                    )
                )
                if need_pf:
                    try:
                        from services.payfast_payin_guard import verify_payfast_ready_for_payout

                        pf_ok, pf_err, resp = await verify_payfast_ready_for_payout(
                            dict(order), require_uuid=True
                        )
                    except Exception as e:
                        logger.warning(
                            "expire payfast check failed order=%s: %s", order_id, e
                        )
                        pf_ok, pf_err = False, "payfast_api_error"

                action = decide_stale_payin_action(
                    ops_pending=ops_pending,
                    ops_pending_fresh=receipt_ops_pending_is_fresh(dict(order)),
                    pf_ok=pf_ok,
                    pf_err=pf_err,
                    has_sibling_paid=bool(sibling),
                    video_hold=is_video_hold(dict(order)),
                )
                if action == ACTION_SUPERSEDE and sibling:
                    await close_superseded_payin(dict(order), sibling, bot=bot)
                    continue
                if action == ACTION_HOLD_OPS:
                    from datetime import datetime, timedelta, timezone
                    from services.db import extend_order_expires_at

                    await extend_order_expires_at(
                        order_id,
                        datetime.now(timezone.utc) + timedelta(minutes=30),
                    )
                    logger.info(
                        "expire skip receipt-ops-pending %s",
                        _order_trace(dict(order)),
                    )
                    continue
                if action == ACTION_COMPLETE:
                    if sibling_lookup_failed:
                        from datetime import datetime, timedelta, timezone
                        from services.db import extend_order_expires_at

                        await extend_order_expires_at(
                            order_id,
                            datetime.now(timezone.utc) + timedelta(minutes=30),
                        )
                        logger.warning(
                            "expire skip complete: sibling lookup failed %s",
                            _order_trace(dict(order)),
                        )
                        continue
                    completed = await complete_stale_ops_pending_if_settled(
                        dict(order),
                        verified_payfast_response=resp,
                    )
                    if completed:
                        continue
                    logger.info(
                        "expire skip payfast-settled (complete failed) %s",
                        _order_trace(dict(order)),
                    )
                    continue
                if action == ACTION_SKIP_SETTLED:
                    logger.info(
                        "expire skip payfast-settled %s",
                        _order_trace(dict(order)),
                    )
                    continue

                if (
                    order.get("direction") == "buy"
                    and order["status"] in ("AWAITING_CHECK", "PENDING")
                    and action == ACTION_HOLD_PF
                ):
                    try:
                        from services.payfast_payin_guard import (
                            PAYFAST_REVIEW_HOLD_REASONS,
                            handle_payfast_recheck,
                            is_payfast_appeal_active,
                            keep_order_alive_for_payfast_review,
                        )

                        if pf_err in PAYFAST_REVIEW_HOLD_REASONS:
                            await keep_order_alive_for_payfast_review(
                                dict(order), resp, pf_err=pf_err, source="expirer"
                            )
                            logger.info(
                                "expire skip %s %s",
                                pf_err,
                                _order_trace(dict(order)),
                            )
                            continue
                        if pf_err == "payfast_recheck_requested" and is_payfast_appeal_active(
                            resp
                        ):
                            await handle_payfast_recheck(
                                dict(order), resp, source="expirer"
                            )
                            logger.info(
                                "expire skip payfast-recheck %s",
                                _order_trace(dict(order)),
                            )
                            continue
                        if pf_err == "payfast_api_error":
                            from datetime import datetime, timedelta, timezone
                            from services.db import extend_order_expires_at

                            await extend_order_expires_at(
                                order_id,
                                datetime.now(timezone.utc) + timedelta(minutes=5),
                            )
                            logger.warning(
                                "expire deferred: Payfast unavailable order=%s",
                                order_id,
                            )
                            continue
                    except Exception as e:
                        logger.warning(
                            "expire payfast hold failed order=%s: %s", order_id, e
                        )
                        from datetime import datetime, timedelta, timezone
                        from services.db import extend_order_expires_at

                        await extend_order_expires_at(
                            order_id,
                            datetime.now(timezone.utc) + timedelta(minutes=5),
                        )
                        continue

                # Клиент записывает видео или ищет PDF — убивать заявку нельзя,
                # даже если Payfast уже снял флаг доп. проверки. Явный отказ
                # провайдера (CANCELED/EXPIRED/REJECTED) ждать не заставляем.
                receipt_wait_over = False
                provider_rejected = str(pf_err or "").startswith("payfast_status_")
                receipt_wait_until = (
                    None if provider_rejected else _receipt_wait_deadline(dict(order))
                )
                if receipt_wait_until is not None:
                    from datetime import datetime, timezone

                    if receipt_wait_until > datetime.now(timezone.utc):
                        from services.db import extend_order_expires_at

                        await extend_order_expires_at(order_id, receipt_wait_until)
                        logger.info(
                            "expire skip receipt-wait %s until=%s",
                            _order_trace(dict(order)),
                            receipt_wait_until.isoformat(),
                        )
                        continue
                    receipt_wait_over = True
                    logger.warning(
                        "receipt wait window over %s",
                        _order_trace(dict(order)),
                    )

                if order.get("direction") == "buy" and (
                    order.get("merchant_order_id") or order.get("order_id")
                ):
                    try:
                        from services.merchant_api_helpers import cancel_payin_for_order

                        await cancel_payin_for_order(dict(order), cancel_order_merchant)
                    except Exception as e:
                        logger.warning(
                            "cancel_order_merchant on expire %s: %s", order_id, e
                        )

                if not await update_order_status(order_id, "EXPIRED"):
                    logger.warning("expire transition rejected for %s", order_id)
                    continue

                logger.info("expired %s pf_err=%s", _order_trace(dict(order)), pf_err)
                if receipt_wait_over:
                    await _notify_ops_receipt_wait_expired(dict(order), bot)

                try:
                    from services.buyer_access_guards import format_expire_followup_message
                    from services.db import get_buyer_payfast_conversion
                    from services.menu import main_menu_keyboard

                    menu = await main_menu_keyboard(row["user_id"])
                    conv = None
                    try:
                        conv = await get_buyer_payfast_conversion(int(row["user_id"]))
                    except Exception:
                        conv = None
                    await bot.send_message(
                        chat_id=row["user_id"],
                        text=format_expire_followup_message(conv),
                        parse_mode="HTML",
                        reply_markup=menu,
                    )
                except Exception as e:
                    logger.warning("expire notify user %s: %s", order_id, e)

                await asyncio.sleep(NOTIFY_DELAY)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("expire_orders_task error: %s", e)

        if shutdown_event is not None:
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=CHECK_INTERVAL,
                )
                break
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
        else:
            try:
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
        if shutdown_event and shutdown_event.is_set():
            break
