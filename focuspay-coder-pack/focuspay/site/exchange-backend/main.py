import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from access_log_middleware import AccessLogMiddleware
from rate_limit_middleware import RateLimitMiddleware

from config import settings, validate_production_config
from db import init_db, close_db
from onion_access import ONION_ORIGIN_REGEX, doliv_onion_url, public_onion_url
from routers import (
    public,
    auth_router,
    orders,
    user_cashback,
    user_balance,
    user_referral,
    user_reviews,
    battle,
    user_casino,
    admin_orders,
    admin_stats,
    admin_dashboard,
    admin_misses,
    admin_payroll,
    admin_expenses,
    admin_recurring_expenses,
    admin_promo,
    admin_referral_partners,
    admin_users,
    admin_operators,
    admin_balances,
    admin_operator_payroll,
    admin_security,
    admin_pricing,
    admin_usdt_issuance,
    operator,
    operator_external,
    operator_casino_payouts,
    operator_order_history,
    operator_payout_requisites,
    operator_promo,
    partner,
    exchanger,
    web_orders,
    chat_public,
    chat_admin,
    chat_operator,
    chat_internal,
    chat_exchanger,
    internal_external,
    internal_casino,
    internal_vpn,
    internal_author_promo,
    casino_creator,
    admin_casino,
    operator_reviews,
    admin_reviews,
    admin_broadcast,
    admin_raffle,
    admin_external,
    admin_exchanger_bot,
    operator_broadcast,
    operator_ai,
    admin_ai,
    deploy_internal,
    operator_changelog,
    operator_antispam,
    admin_sticker_ai,
    exchanger_bot_webhook,
    exchanger_v1,
    public_casino,
    nardy,
    draughts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")


async def _settings_refresh_loop():
    from runtime_settings import refresh_settings

    while True:
        try:
            await refresh_settings(force=True)
        except Exception:
            logger.exception("runtime settings refresh failed")
        await asyncio.sleep(30)


async def _signer_policy_sync_loop():
    """Держать потолки LTC/BTC на подписанте в синхронизации с админкой автопилота."""
    from signer_client import push_signer_policy, signer_configured

    await asyncio.sleep(5)
    while True:
        try:
            if signer_configured():
                await push_signer_policy()
        except Exception:
            logger.exception("signer policy sync failed")
        await asyncio.sleep(60)


async def _reviews_sync_loop():
    from reviews_sync import sync_reviews_from_public_channel

    while True:
        try:
            await sync_reviews_from_public_channel(force=True)
        except Exception:
            logger.exception("reviews background sync failed")
        await asyncio.sleep(900)


async def _admin_salary_loop():
    """Раз в час проверяем, начислена ли дневная зарплата админ-персоналу."""
    from admin_salary import accrue_due_salaries

    # Старт через минуту после поднятия API
    await asyncio.sleep(60)
    while True:
        try:
            n = await accrue_due_salaries()
            if n:
                logger.info("Admin salary auto-accrual: %s entries", n)
        except Exception:
            logger.exception("admin salary accrual failed")
        await asyncio.sleep(3600)


async def _casino_cashback_loop():
    """Раз в сутки проверяем, нужно ли начислить недельный кешбек казино."""
    from casino_weekly_cashback import accrue_weekly_casino_cashback
    from datetime import datetime

    # Старт через 2 минуты после поднятия API
    await asyncio.sleep(120)
    while True:
        try:
            now = datetime.now()
            # Запускать в понедельник утром (weekday 0 = понедельник)
            if now.weekday() == 0 and now.hour == 6:
                logger.info("Starting casino weekly cashback accrual...")
                result = await accrue_weekly_casino_cashback()
                logger.info(
                    f"Casino cashback complete: {result['accrued']} players, "
                    f"{result['total_cashback_rub']:.2f} ₽"
                )
        except Exception:
            logger.exception("casino cashback accrual failed")
        # Проверять раз в час
        await asyncio.sleep(3600)


async def _battle_scheduler_loop():
    from battle_service import get_battle_manager

    manager = await get_battle_manager()
    while True:
        try:
            await manager.lock_if_needed()
            await manager.resolve_due_rounds()
        except Exception:
            logger.exception("battle scheduler tick failed")
        await asyncio.sleep(1)


async def _captcha_cleanup_loop():
    """Удаление старых captcha challenges (старше 1 часа) каждые 10 минут."""
    from db import get_pool

    while True:
        try:
            await asyncio.sleep(600)  # 10 минут
            pool = await get_pool()
            async with pool.acquire() as conn:
                deleted = await conn.fetchval(
                    """
                    DELETE FROM captcha_challenges
                    WHERE created_at < now() - interval '1 hour'
                    RETURNING COUNT(*)
                    """
                )
                if deleted and deleted > 0:
                    logger.info("Captcha cleanup: deleted %d old challenges", deleted)
        except Exception:
            logger.exception("captcha cleanup failed")


async def _business_digest_loop():
    """Проверять due delivery независимо от фазы запуска worker-а."""
    from business_digest import send_business_digest

    await asyncio.sleep(180)  # Старт через 3 минуты после поднятия API
    while True:
        try:
            success = await send_business_digest()
            if success:
                logger.info("Business digest sent successfully")
        except Exception:
            logger.exception("business digest loop failed")
        await asyncio.sleep(300)


async def _operator_digest_loop():
    """Отправка личных дайджестов операторам по их расписанию."""
    from ops_ai_memory import run_due_digests

    await asyncio.sleep(240)  # Старт через 4 минуты после поднятия API

    while True:
        try:
            # Проверять каждый час, есть ли операторы с текущим digest_hour
            sent = await run_due_digests()
            if sent:
                logger.info("Operator digests sent: %d", sent)
        except Exception:
            logger.exception("operator digest loop failed")
        await asyncio.sleep(300)  # Retry failures within the configured hour


async def _payout_requisite_loop():
    """Подбор чеков под реквизиты выплат + snap-цели для котировок SELL."""
    from payout_requisite_loop import payout_requisite_loop

    await payout_requisite_loop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_config()
    logger.info("Connecting to database...")
    await init_db(settings.database_dsn)
    logger.info("DB pool ready.")
    try:
        from casino_raffle import ensure_closer as raffle_ensure_closer

        raffle_ensure_closer()
    except Exception:
        logger.exception("raffle closer failed to start")
    try:
        from casino_v2_web import ensure_closer as v2_web_ensure_closer

        v2_web_ensure_closer()
    except Exception:
        logger.exception("v2 closer failed to start")
    try:
        from casino_tournaments import ensure_closer as tournaments_ensure_closer

        tournaments_ensure_closer()
    except Exception:
        logger.exception("tournament closer failed to start")
    if settings.staging_disable_background_tasks:
        if (settings.environment or "").strip().lower() != "staging":
            raise RuntimeError("STAGING_DISABLE_BACKGROUND_TASKS requires ENVIRONMENT=staging")
        logger.warning("Staging background tasks, listeners, and external bridges are disabled")
        from runtime_settings import refresh_settings

        await refresh_settings(force=True)
        from bot_status_bridge import init_bot_status_bridge

        if not await init_bot_status_bridge(settings.database_dsn):
            logger.error(
                "Bot status bridge failed — operator payout and status hooks unavailable on staging"
            )
        else:
            logger.warning("Bot status bridge still runs on staging (SELL paid + payout receipts)")
        payout_requisite_task = asyncio.create_task(_payout_requisite_loop())
        logger.warning("Payout requisite matcher still runs on staging (plans + snap targets)")
        try:
            yield
        finally:
            payout_requisite_task.cancel()
            try:
                await payout_requisite_task
            except asyncio.CancelledError:
                pass
            await close_db()
            logger.info("DB pool closed.")
        return
    from bot_status_bridge import init_bot_status_bridge
    from review_bot_bridge import init_review_bot_bridge

    if not await init_bot_status_bridge(settings.database_dsn):
        logger.error(
            "Bot status bridge failed — operator payout and status hooks unavailable"
        )
    if not await init_review_bot_bridge(settings.database_dsn):
        logger.warning("Review bot bridge unavailable — web review moderation disabled")
    from broadcast_service import recover_stale_jobs, scheduler_loop

    await recover_stale_jobs()
    from exchanger_bot_config import ensure_webhook_on_startup

    await ensure_webhook_on_startup()
    from runtime_settings import refresh_settings

    await refresh_settings(force=True)
    from chat_events_hub import start_chat_events_listener

    await start_chat_events_listener()
    from buyer_events_hub import start_buyer_events_listener

    await start_buyer_events_listener()
    settings_task = asyncio.create_task(_settings_refresh_loop())
    signer_policy_task = asyncio.create_task(_signer_policy_sync_loop())
    sync_task = asyncio.create_task(_reviews_sync_loop())
    salary_task = asyncio.create_task(_admin_salary_loop())
    casino_cashback_task = asyncio.create_task(_casino_cashback_loop())
    captcha_cleanup_task = asyncio.create_task(_captcha_cleanup_loop())
    business_digest_task = asyncio.create_task(_business_digest_loop())
    operator_digest_task = asyncio.create_task(_operator_digest_loop())
    payout_requisite_task = asyncio.create_task(_payout_requisite_loop())
    from hot_wallet_monitor import hot_wallet_monitor_loop
    from auto_payout_worker import auto_payout_worker_loop

    hot_wallet_task = asyncio.create_task(hot_wallet_monitor_loop())
    from casino_crypto_deposit import casino_crypto_deposit_loop

    crypto_deposit_task = asyncio.create_task(casino_crypto_deposit_loop())
    auto_payout_task = asyncio.create_task(auto_payout_worker_loop())
    battle_task = None
    if settings.battle_enabled:
        battle_task = asyncio.create_task(_battle_scheduler_loop())
    from exchanger_chat_escalation import exchanger_escalation_sweeper_loop

    escalation_task = asyncio.create_task(exchanger_escalation_sweeper_loop())
    broadcast_task = asyncio.create_task(scheduler_loop())
    from vpn_billing import reconcile_loop as vpn_reconcile_loop

    vpn_reconcile_task = asyncio.create_task(vpn_reconcile_loop())
    from casino_draughts import timeout_loop as draughts_timeout_loop

    draughts_timeout_task = asyncio.create_task(draughts_timeout_loop())
    yield
    draughts_timeout_task.cancel()
    vpn_reconcile_task.cancel()
    settings_task.cancel()
    signer_policy_task.cancel()
    sync_task.cancel()
    salary_task.cancel()
    casino_cashback_task.cancel()
    captcha_cleanup_task.cancel()
    business_digest_task.cancel()
    operator_digest_task.cancel()
    payout_requisite_task.cancel()
    hot_wallet_task.cancel()
    crypto_deposit_task.cancel()
    auto_payout_task.cancel()
    escalation_task.cancel()
    broadcast_task.cancel()
    if battle_task:
        battle_task.cancel()
    try:
        await settings_task
    except asyncio.CancelledError:
        pass
    try:
        await signer_policy_task
    except asyncio.CancelledError:
        pass
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    try:
        await salary_task
    except asyncio.CancelledError:
        pass
    try:
        await casino_cashback_task
    except asyncio.CancelledError:
        pass
    try:
        await payout_requisite_task
    except asyncio.CancelledError:
        pass
    try:
        await crypto_deposit_task
    except asyncio.CancelledError:
        pass
    try:
        await escalation_task
    except asyncio.CancelledError:
        pass
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    if battle_task:
        try:
            await battle_task
        except asyncio.CancelledError:
            pass
    from chat_events_hub import stop_chat_events_listener

    await stop_chat_events_listener()
    from buyer_events_hub import stop_buyer_events_listener

    await stop_buyer_events_listener()
    await close_db()
    logger.info("DB pool closed.")


_docs_url = "/docs" if settings.expose_openapi_docs else None
_openapi_url = "/openapi.json" if settings.expose_openapi_docs else None
app = FastAPI(
    title="FocusPay Exchange API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    openapi_url=_openapi_url,
    redoc_url=None,
)

_cors_origins: list[str] = []
_site = (settings.public_site_url or "").rstrip("/")
if _site:
    _cors_origins.append(_site)
for extra in (public_onion_url(), doliv_onion_url()):
    if extra and extra not in _cors_origins:
        _cors_origins.append(extra)
if settings.expose_local_cors:
    for origin in ("http://localhost:5173", "http://localhost:3000"):
        if origin not in _cors_origins:
            _cors_origins.append(origin)
for origin in (settings.cors_origins or "").split(","):
    o = origin.strip().rstrip("/")
    if o and o not in _cors_origins:
        _cors_origins.append(o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["https://focuspay.org"],
    allow_origin_regex=ONION_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(public.router,        prefix="/api/public",  tags=["Public"])
app.include_router(public_casino.router, prefix="/api/public",  tags=["Public Casino"])
app.include_router(nardy.public_router, prefix="/api/public", tags=["Public Casino"])
app.include_router(draughts.public_router, prefix="/api/public", tags=["Public Casino"])
app.include_router(web_orders.router,    prefix="/api/public",  tags=["Public Orders"])
app.include_router(chat_public.router,   prefix="/api/public",  tags=["Public Chat"])
app.include_router(chat_admin.router,    prefix="/api/admin",   tags=["Admin Chat"])
app.include_router(chat_operator.router, prefix="/api/operator", tags=["Operator Chat"])
app.include_router(chat_internal.router, prefix="/api/internal", tags=["Internal"])
app.include_router(internal_external.router, prefix="/api/internal", tags=["Internal"])
app.include_router(internal_casino.router, prefix="/api/internal/casino", tags=["Internal Casino"])
app.include_router(internal_vpn.router, prefix="/api/internal/vpn", tags=["Internal VPN"])
app.include_router(internal_author_promo.router, prefix="/api/internal", tags=["Internal Author Promo"])
app.include_router(deploy_internal.router, prefix="/api/internal", tags=["Deploy"])
app.include_router(auth_router.router,   prefix="/api/auth",    tags=["Auth"])
app.include_router(orders.router,        prefix="/api/user",    tags=["User"])
app.include_router(user_cashback.router, prefix="/api/user",    tags=["User"])
app.include_router(user_balance.router, prefix="/api/user",    tags=["User"])
app.include_router(user_referral.router, prefix="/api/user",    tags=["User"])
app.include_router(user_reviews.router,  prefix="/api/user",    tags=["User"])
app.include_router(battle.router,       prefix="/api/user",    tags=["User Battle"])
app.include_router(user_casino.router,  prefix="/api/user",    tags=["User Casino"])
app.include_router(nardy.user_router, prefix="/api/user", tags=["User Casino"])
app.include_router(draughts.user_router, prefix="/api/user", tags=["User Casino"])
app.include_router(admin_orders.router,  prefix="/api/admin",   tags=["Admin"])
app.include_router(admin_stats.router,   prefix="/api/admin",   tags=["Admin"])
app.include_router(admin_dashboard.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_misses.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_payroll.router,    prefix="/api/admin",    tags=["Admin"])
app.include_router(admin_expenses.router,   prefix="/api/admin",    tags=["Admin"])
app.include_router(admin_recurring_expenses.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_promo.router,     prefix="/api/admin",    tags=["Admin"])
app.include_router(admin_referral_partners.router, prefix="/api/admin", tags=["Admin Referral"])
app.include_router(admin_users.router,     prefix="/api/admin",    tags=["Admin"])
app.include_router(admin_operators.router, prefix="/api/admin",    tags=["Admin"])
app.include_router(admin_balances.router,   prefix="/api/admin",    tags=["Admin"])
app.include_router(admin_operator_payroll.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_security.router,      prefix="/api/admin", tags=["Admin Security"])
app.include_router(admin_pricing.router,       prefix="/api/admin", tags=["Admin Pricing"])
from routers import admin_autopilot

app.include_router(admin_autopilot.router, prefix="/api/admin", tags=["Admin Autopilot"])
from routers import admin_vpn

app.include_router(admin_vpn.router, prefix="/api/admin", tags=["Admin VPN"])
app.include_router(admin_usdt_issuance.router, prefix="/api/admin", tags=["Admin USDT"])
app.include_router(admin_reviews.router,       prefix="/api/admin", tags=["Admin Reviews"])
app.include_router(admin_broadcast.router,     prefix="/api/admin", tags=["Admin Broadcast"])
app.include_router(admin_raffle.router,        prefix="/api/admin", tags=["Admin FocusLucky"])
app.include_router(admin_external.router,      prefix="/api/admin", tags=["Admin External"])
app.include_router(admin_exchanger_bot.router, prefix="/api/admin", tags=["Admin Exchanger Bot"])
app.include_router(operator_order_history.router, prefix="/api/operator", tags=["Operator Order History"])
app.include_router(operator.router,        prefix="/api/operator", tags=["Operator"])
app.include_router(operator_external.router, prefix="/api/operator", tags=["Operator External"])
app.include_router(operator_casino_payouts.router, prefix="/api/operator", tags=["Operator Casino Payouts"])
app.include_router(operator_payout_requisites.router, prefix="/api/operator", tags=["Operator Payout Requisites"])
app.include_router(operator_promo.router,  prefix="/api/operator", tags=["Operator Promo"])
app.include_router(operator_reviews.router, prefix="/api/operator", tags=["Operator Reviews"])
app.include_router(operator_broadcast.router, prefix="/api/operator", tags=["Operator Broadcast"])
app.include_router(operator_ai.router, prefix="/api/operator", tags=["Operator AI"])
app.include_router(operator_changelog.router, prefix="/api/operator", tags=["Operator Changelog"])
app.include_router(operator_antispam.router, prefix="/api/operator", tags=["Operator Antispam"])
app.include_router(admin_ai.router, prefix="/api/admin", tags=["Admin AI"])
app.include_router(admin_sticker_ai.router, prefix="/api/admin", tags=["Admin Sticker AI"])
app.include_router(partner.router,         prefix="/api/partner",  tags=["Partner"])
app.include_router(exchanger_v1.router,    prefix="/api/exchanger/v1", tags=["Exchanger HMAC"])
app.include_router(exchanger.router,       prefix="/api/exchanger", tags=["Exchanger"])
app.include_router(chat_exchanger.router,    prefix="/api/exchanger", tags=["Exchanger Chat"])
app.include_router(exchanger_bot_webhook.router, prefix="/api/bot", tags=["Exchanger Bot"])
app.include_router(casino_creator.router, prefix="/api/casino/creator", tags=["Casino Creator"])
app.include_router(admin_casino.router, prefix="/api/admin", tags=["Admin Casino"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
