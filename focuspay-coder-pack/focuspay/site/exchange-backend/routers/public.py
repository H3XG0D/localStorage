import asyncio
import json
import logging
import socket
import time
from pathlib import Path

import aiohttp
from pydantic import BaseModel, Field
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from commission import commission_percent
from config import settings
from db import get_pool
from referral_links import (
    telegram_deep_link,
    user_telegram_deep_link,
    web_ref_link,
    web_user_invite_link,
)
from onion_access import doliv_onion_url, public_onion_url
from panel_cookies import guest_session_trusted
from telegram_oauth import build_telegram_oauth_url
from reviews_sync import list_reviews, sync_reviews_from_public_channel
from client_ip import get_client_ip
from web_attribution import track_ref_visit

router = APIRouter()
logger = logging.getLogger("public")

RAPIRA_URL = "https://api.rapira.net/open/market/rates"
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,litecoin,tron&vs_currencies=usd"
)
COINGECKO_IDS = {"btc": "bitcoin", "ltc": "litecoin", "trx": "tron"}
COINGECKO_RUB_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=tether,bitcoin,litecoin,tron&vs_currencies=rub"
)
COINGECKO_RUB_IDS = {
    "usdt": "tether",
    "btc": "bitcoin",
    "ltc": "litecoin",
    "trx": "tron",
}
SUPPORTED = ("btc", "usdt", "trx", "ltc")

_cache: dict = {}
_CACHE_TTL = 60
_LAST_SOURCE = "none"
USDT_EARN_PAD = 2.0
FROZEN_USDT_PAD = 0.5
_fetch_lock = asyncio.Lock()
_bg_refresh: asyncio.Task | None = None
# Shared keepalive session: Rapira SYN-drops a large share of NEW connections
# from prod IP, while reused connections are stable. One session per process,
# rebuilt lazily if closed or on connection-level errors.
_RAPIRA_CONNECTOR: aiohttp.TCPConnector | None = None
_RAPIRA_SESSION: aiohttp.ClientSession | None = None
_need_cache: dict = {}
_NEED_TTL = 60
_NEED_FAIL_TTL = 20
_need_fail_ts = 0.0
_need_lock = asyncio.Lock()
_SNAPSHOT_PATHS = (
    Path("/opt/tg_bot_btc/data/rapira_rates_snapshot.json"),
    Path("/opt/exchange-backend/data/rapira_rates_snapshot.json"),
)


def _rates_only(src: dict) -> dict:
    return {k: float(v) for k, v in src.items() if k != "_ts" and isinstance(v, (int, float)) and float(v) > 0}


def _cached_rates(*, allow_stale: bool = False) -> dict | None:
    if not _cache:
        return None
    age = time.time() - float(_cache.get("_ts") or 0)
    if allow_stale or age < _CACHE_TTL:
        out = _rates_only(_cache)
        return out or None
    return None


def rates_source() -> str:
    return _LAST_SOURCE


def _shift_usdt(market: dict | None, delta: float) -> dict:
    out = dict(market or {})
    try:
        usdt = float(out.get("usdt") or 0)
    except (TypeError, ValueError):
        return out
    if usdt > 0:
        shifted = usdt + delta
        if shifted > 0:
            out["usdt"] = shifted
    return out


def _buy_usdt_delta(*, source: str | None = None) -> float:
    src = rates_source() if source is None else source
    delta = USDT_EARN_PAD
    if src == "frozen":
        delta += FROZEN_USDT_PAD
    return delta


def _with_buy_usdt_pad(market: dict | None, *, source: str | None = None) -> dict:
    """USDT serve pad for BUY. RAM cache and snapshot stay raw."""
    return _shift_usdt(market, _buy_usdt_delta(source=source))


def _with_sell_usdt_pad(market: dict | None) -> dict:
    return _shift_usdt(market, -USDT_EARN_PAD)


def _with_frozen_usdt_pad(market: dict | None) -> dict:
    return _with_buy_usdt_pad(market)


def _store_rates(market: dict, source: str = "rapira") -> None:
    global _LAST_SOURCE
    _LAST_SOURCE = source
    _cache.clear()
    _cache["_ts"] = time.time()
    for k, v in market.items():
        _cache[k] = v


def _load_snapshot_rates() -> dict | None:
    for path in _SNAPSHOT_PATHS:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        payload = raw.get("rates") if isinstance(raw, dict) and isinstance(raw.get("rates"), dict) else raw
        if not isinstance(payload, dict):
            continue
        out: dict[str, float] = {}
        for key in SUPPORTED:
            try:
                val = float(payload.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if val > 0:
                out[key] = val
        if "usdt" in out:
            return out
    return None


async def _fetch_rapira_only(*, attempts: int = 4) -> dict:
    """Rapira close only — no CoinGecko fill. Retries transient stalls.

    Uses a shared keepalive session: Rapira SYN-drops a large share of NEW
    TCP connects from prod IP, while reused connections stay stable.
    Frozen snapshot remains the fallback.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            session = await _rapira_session()
            async with session.get(RAPIRA_URL) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Rapira HTTP {resp.status}")
                body = await asyncio.wait_for(resp.json(), timeout=10)
            return _parse_rapira_body(body)
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientConnectionError) as e:
            last_error = e
            logger.warning(
                "Rapira connection lost on attempt %s/%s, rebuilding session",
                attempt, attempts,
            )
            await _close_rapira_session()
            if attempt < attempts:
                await asyncio.sleep(1.5)
        except Exception as e:
            last_error = e
            logger.warning("Rapira fetch attempt %s/%s failed: %s", attempt, attempts, e)
            if attempt < attempts:
                await asyncio.sleep(1.5)
    raise RuntimeError(f"Rapira unreachable after {attempts} attempts: {last_error}")


def _rapira_connector() -> aiohttp.TCPConnector:
    global _RAPIRA_CONNECTOR
    if _RAPIRA_CONNECTOR is None or _RAPIRA_CONNECTOR.closed:
        _RAPIRA_CONNECTOR = aiohttp.TCPConnector(
            limit=5,
            limit_per_host=2,
            ttl_dns_cache=300,
            family=socket.AF_INET,
            keepalive_timeout=60,
        )
    return _RAPIRA_CONNECTOR


async def _rapira_session() -> aiohttp.ClientSession:
    global _RAPIRA_SESSION
    if _RAPIRA_SESSION is None or _RAPIRA_SESSION.closed:
        _RAPIRA_SESSION = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20, connect=10),
            connector=_rapira_connector(),
        )
    return _RAPIRA_SESSION


async def _close_rapira_session() -> None:
    global _RAPIRA_SESSION, _RAPIRA_CONNECTOR
    if _RAPIRA_SESSION is not None:
        try:
            await _RAPIRA_SESSION.close()
        except Exception:
            pass
        _RAPIRA_SESSION = None
    if _RAPIRA_CONNECTOR is not None:
        try:
            await _RAPIRA_CONNECTOR.close()
        except Exception:
            pass
        _RAPIRA_CONNECTOR = None


def _parse_rapira_body(body) -> dict[str, float]:
    data = (body or {}).get("data", [])
    by_sym = {(item or {}).get("symbol"): item for item in data if item}

    usdt_item = by_sym.get("USDT/RUB")
    if not usdt_item:
        raise RuntimeError("USDT/RUB not in Rapira response")
    usdt_rub = float(usdt_item["close"])

    market: dict[str, float] = {"usdt": usdt_rub}
    for pair, key in (("BTC/USDT", "btc"), ("LTC/USDT", "ltc"), ("TRX/USDT", "trx")):
        item = by_sym.get(pair)
        if item and float(item.get("close", 0)) > 0:
            market[key] = float(item["close"]) * usdt_rub
    return market


async def _fill_missing_from_coingecko(market: dict) -> dict:
    """CoinGecko USD fill for missing Rapira pairs (public BUY only)."""
    out = dict(market)
    missing = [k for k in COINGECKO_IDS if k not in out]
    if not missing:
        return out
    usdt_rub = float(out.get("usdt") or 0)
    if usdt_rub <= 0:
        # No USDT anchor: fill directly from CoinGecko RUB cache instead of giving up.
        try:
            rub = await get_need_rates_cached()
        except Exception:
            rub = {}
        for key in missing:
            try:
                val = float((rub or {}).get(key) or 0)
            except (TypeError, ValueError):
                val = 0
            if val > 0:
                out[key] = val
                logger.info("%s/RUB via CoinGecko RUB cache (no USDT anchor)", key.upper())
        return out
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get(COINGECKO_URL) as cg:
                if cg.status != 200:
                    return out
                cg_body = await cg.json()
                for key, cg_id in COINGECKO_IDS.items():
                    if key in out:
                        continue
                    usd = float((cg_body or {}).get(cg_id, {}).get("usd", 0))
                    if usd > 0:
                        out[key] = usd * usdt_rub
                        logger.info("%s/RUB via CoinGecko: %s USD", key.upper(), usd)
    except Exception as e:
        logger.warning("CoinGecko fallback failed: %s", e)
    return out


async def _fetch_rates() -> dict:
    """Rapira + CoinGecko fill — legacy alias for public paths."""
    return await _fill_missing_from_coingecko(await _fetch_rapira_only())


def parse_coingecko_rub(body) -> dict[str, float]:
    if not isinstance(body, dict):
        return {}
    out: dict[str, float] = {}
    for key, cg_id in COINGECKO_RUB_IDS.items():
        try:
            rub = float((body.get(cg_id) or {}).get("rub") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if rub > 0:
            out[key] = rub
    return out


def _need_rates_only(src: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in SUPPORTED:
        try:
            val = float(src.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if val > 0:
            out[key] = val
    return out


def _store_need(rates: dict[str, float]) -> None:
    _need_cache.clear()
    _need_cache["_ts"] = time.time()
    for key, val in rates.items():
        _need_cache[key] = val


async def _fetch_coingecko_rub() -> dict[str, float]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.get(COINGECKO_RUB_URL) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CoinGecko HTTP {resp.status}")
            body = await resp.json()
    return parse_coingecko_rub(body)


async def get_need_rates_cached() -> dict[str, float]:
    """CoinGecko RUB for BUY+RUB quotes. Empty dict if unavailable."""
    global _need_fail_ts
    age = time.time() - float(_need_cache.get("_ts") or 0)
    fresh = _need_rates_only(_need_cache)
    if fresh and age < _NEED_TTL and all(k in fresh for k in SUPPORTED):
        return fresh
    async with _need_lock:
        age = time.time() - float(_need_cache.get("_ts") or 0)
        fresh = _need_rates_only(_need_cache)
        if fresh and age < _NEED_TTL and all(k in fresh for k in SUPPORTED):
            return fresh
        now = time.time()
        if _need_fail_ts and now - _need_fail_ts < _NEED_FAIL_TTL:
            return fresh
        try:
            fetched = _need_rates_only(await _fetch_coingecko_rub())
        except Exception as e:
            _need_fail_ts = now
            logger.warning("CoinGecko RUB fetch failed: %s", e)
            fetched = {}
        if fetched and all(k in fetched for k in SUPPORTED):
            _store_need(fetched)
            _need_fail_ts = 0.0
            return fetched
        if all(k in fresh for k in SUPPORTED):
            logger.warning("Using stale CoinGecko RUB rates")
            return fresh
        if fetched:
            _store_need(fetched)
            return fetched
        _need_fail_ts = now
        return fresh


async def _refresh_from_rapira() -> None:
    try:
        market = await _fetch_rapira_only()
        _store_rates(market, source="rapira")
    except Exception as e:
        global _LAST_SOURCE
        if _cache:
            _LAST_SOURCE = "frozen"
        logger.warning("Rapira refresh failed: %s", e)


def _schedule_refresh() -> None:
    global _bg_refresh
    if _bg_refresh is not None and not _bg_refresh.done():
        return
    _bg_refresh = asyncio.create_task(_refresh_from_rapira())


async def _ensure_raw_rapira() -> dict:
    """Live Rapira if fresh; otherwise last snapshot. Unpadded."""
    cached = _cached_rates()
    if cached:
        return cached
    async with _fetch_lock:
        cached = _cached_rates()
        if cached:
            return cached
        memory_stale = _cached_rates(allow_stale=True)
        snapshot = _load_snapshot_rates()
        stale = memory_stale or snapshot
        if stale:
            source = "frozen" if not memory_stale or _LAST_SOURCE != "rapira" else "rapira"
            if source == "frozen":
                logger.warning("Using frozen Rapira snapshot for calculator/API")
            _store_rates(stale, source=source)
            _schedule_refresh()
            return stale
        try:
            market = await _fetch_rapira_only()
            _store_rates(market, source="rapira")
            return market
        except Exception as e:
            logger.error("Failed to fetch rates: %s", e)
            raise


async def get_rates_cached() -> dict:
    """Live Rapira if fresh; otherwise last snapshot (same file as the bot).

    Never drops coins: merges live + snapshot per-coin, then CoinGecko fill.
    May return a partial dict — callers must fall back per-coin, not 404.
    """
    rapira = await _ensure_raw_rapira()
    snapshot = _load_snapshot_rates() or {}
    merged: dict[str, float] = dict(rapira)
    for key in SUPPORTED:
        try:
            val = float(merged.get(key) or 0)
        except (TypeError, ValueError):
            val = 0
        if val <= 0 and float(snapshot.get(key) or 0) > 0:
            merged[key] = float(snapshot[key])
    filled = await _fill_missing_from_coingecko(merged)
    # last chance: snapshot per-coin after CoinGecko fill
    for key in SUPPORTED:
        try:
            val = float(filled.get(key) or 0)
        except (TypeError, ValueError):
            val = 0
        if val <= 0 and float(snapshot.get(key) or 0) > 0:
            filled[key] = float(snapshot[key])
    return _with_buy_usdt_pad(filled)


async def get_exchanger_rates_cached() -> dict:
    """Raw Rapira close for freelancer cabinet — no USDT pad, no CoinGecko."""
    return await _ensure_raw_rapira()


def merge_sell_market(need: dict | None, rapira: dict | None) -> dict[str, float]:
    """CoinGecko first, Rapira fallback. Missing coins are filled from the other source."""
    need = need or {}
    rapira = rapira or {}
    out: dict[str, float] = {}
    for crypto in SUPPORTED:
        price = need.get(crypto) or rapira.get(crypto)
        if price:
            out[crypto] = float(price)
    return out


async def get_sell_market_rates() -> dict[str, float]:
    """Market RUB for SELL and dolivs: CoinGecko primary, Rapira if CoinGecko is down."""
    need: dict[str, float] = {}
    rapira: dict[str, float] = {}
    try:
        need = await get_need_rates_cached()
    except Exception as e:
        logger.warning("CoinGecko sell market unavailable: %s", e)
    try:
        rapira = await _ensure_raw_rapira()
    except Exception as e:
        logger.warning("Rapira sell fallback unavailable: %s", e)
    merged = merge_sell_market(need, rapira)
    if not merged:
        raise RuntimeError("Sell market rates unavailable")
    return _with_sell_usdt_pad(merged)


@router.get("/site-config")
async def site_config():
    """Публичные настройки для фронтенда (имя бота для Login Widget)."""
    username = (settings.telegram_bot_username or "focuspay1_bot").lstrip("@")
    return {
        "telegram_bot_username": username,
        "public_site_url": settings.public_site_url,
        "public_onion_url": public_onion_url() or None,
        "doliv_onion_url": doliv_onion_url() or None,
    }


@router.get("/telegram-login-url")
async def telegram_login_url(
    origin: str,
    return_path: str = "/login",
):
    """
    URL для входа через Telegram без iframe (Firefox ETP / блокировка third-party cookies).
    origin — window.location.origin с фронта (должен совпадать с доменом в @BotFather /setdomain).
    """
    return {"url": build_telegram_oauth_url(origin, return_path)}


@router.get("/rates")
async def get_rates():
    """
    Returns buy/sell rates for all supported cryptos.
    buy  = Rapira × buy_markup (client pays more)
    sell = CoinGecko (Rapira fallback) × sell_multiplier
           discount: client receives less; markup: we pay extra for their crypto
    """
    try:
        market = await get_rates_cached()
    except Exception as e:
        logger.error(f"Failed to fetch rates: {e}")
        raise HTTPException(status_code=503, detail="Rate service temporarily unavailable")

    import runtime_settings
    from payment_methods_display import public_tariffs_data_async

    need = await get_need_rates_cached()
    try:
        sell_market = await get_sell_market_rates()
    except Exception:
        sell_market = _with_sell_usdt_pad(merge_sell_market(need, _cached_rates() or {}))

    result = {}
    for crypto in SUPPORTED:
        price = market.get(crypto)
        if price is None:
            continue
        auto_m = runtime_settings.buy_markup(manual=False, amount_rub=0)
        sell_d = runtime_settings.sell_discount()
        need_price = need.get(crypto)
        sell_price = sell_market.get(crypto) or price
        result[crypto] = {
            "market": round(price, 2),
            "buy": round(price * auto_m, 2),
            "sell": round(sell_price * sell_d, 2),
            "need": round(need_price, 2) if need_price else None,
            "buy_commission_pct": commission_percent(
                crypto, "buy", manual=False, amount_rub=0
            ),
            "sell_commission_pct": commission_percent(crypto, "sell"),
            "currency": "RUB",
        }

    return {
        "rates": result,
        "public_tariffs": await public_tariffs_data_async(),
        "updated_at": _cache.get("_ts"),
        "source": rates_source(),
        "frozen": rates_source() == "frozen",
        "sell_pricing_mode": runtime_settings.sell_pricing_mode(),
    }


class SellQuoteBody(BaseModel):
    crypto: str
    crypto_amount: Optional[float] = Field(None, gt=0)
    fiat_amount: Optional[float] = Field(None, gt=0)


@router.post("/sell/quote")
async def post_sell_quote(body: SellQuoteBody):
    """Финальная сумма SELL для калькулятора — совпадает с суммой заявки.

    Нужен потому, что сумма может быть подогнана под открытый реквизит выплаты;
    локальный расчёт на фронте такую подгонку не знает.
    """
    crypto = (body.crypto or "").strip().lower()
    if crypto not in SUPPORTED:
        raise HTTPException(status_code=400, detail="Unsupported crypto")
    if (body.crypto_amount is None) == (body.fiat_amount is None):
        raise HTTPException(
            status_code=400, detail="Укажите либо crypto_amount, либо fiat_amount"
        )

    from order_service import quote_sell

    return {
        "quote": await quote_sell(
            crypto,
            fiat_amount=body.fiat_amount,
            crypto_amount=body.crypto_amount,
        )
    }


@router.get("/cryptos")
async def get_cryptos():
    """Returns supported cryptos with their limits."""
    return {
        "cryptos": [
            {
                "id": "btc",
                "name": "Bitcoin",
                "ticker": "BTC",
                "networks": ["mainnet"],
                "limits": settings.amount_limits.get("btc"),
            },
            {
                "id": "usdt",
                "name": "Tether USD",
                "ticker": "USDT",
                "networks": ["TRC20", "ERC20", "BEP20"],
                "limits": settings.amount_limits.get("usdt"),
            },
            {
                "id": "trx",
                "name": "TRON",
                "ticker": "TRX",
                "networks": ["mainnet"],
                "limits": settings.amount_limits.get("trx"),
            },
            {
                "id": "ltc",
                "name": "Litecoin",
                "ticker": "LTC",
                "networks": ["mainnet"],
                "limits": settings.amount_limits.get("ltc"),
            },
        ]
    }


@router.get("/ref/{ref_token}")
async def redirect_ref_link(ref_token: str):
    """
    Единая реф-ссылка: открывает Telegram-бота с автопривязкой.
    Работает и для партнёрских/промо-кампаний, и для обычных рефереров.
    Пример: https://ваш-сайт/ref/a8f3k2m9x1q0w5e7r2
    """
    token = ref_token.strip().lower()
    pool = await get_pool()
    async with pool.acquire() as conn:
        promo = await conn.fetchval(
            """
            SELECT ref_token FROM promo_campaigns
            WHERE ref_token = $1 AND is_active = TRUE
            """,
            token,
        )
        if not promo:
            promo = await conn.fetchval(
                "SELECT ref_token FROM bot_users WHERE ref_token = $1",
                token,
            )
    if not promo:
        raise HTTPException(status_code=404, detail="Referral link not found or inactive")
    return RedirectResponse(telegram_deep_link(promo), status_code=302)


@router.get("/invite/{ref_token}")
async def redirect_invite_link(ref_token: str):
    """Legacy /invite/<token>: перенаправляем на единую /ref/<token>."""
    token = ref_token.strip().lower()
    return RedirectResponse(f"/ref/{token}", status_code=301)


@router.get("/ref/{ref_token}/info")
async def ref_link_info(ref_token: str):
    """JSON для страницы /ref/:token на фронте."""
    token = ref_token.strip().lower()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT code, name, ref_token, bonus_percent
            FROM promo_campaigns
            WHERE ref_token = $1 AND is_active = TRUE
            """,
            token,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Referral link not found")
    return {
        "code": row["code"],
        "name": row["name"],
        "ref_token": row["ref_token"],
        "bonus_percent": float(row["bonus_percent"]),
        "telegram_url": telegram_deep_link(row["ref_token"]),
        "web_url": web_ref_link(row["ref_token"]),
    }


@router.get("/invite/{ref_token}/info")
async def user_invite_info(ref_token: str):
    """Реферальная ссылка обычного пользователя (не промо-кампания)."""
    token = ref_token.strip().lower()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM bot_users WHERE ref_token = $1",
            token,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Invite link not found")
    return {
        "ref_token": token,
        "telegram_url": user_telegram_deep_link(token),
        "web_url": web_user_invite_link(token),
    }


class AttributionTrackBody(BaseModel):
    ref_kind: str = Field(default="auto", pattern="^(promo|user|auto)$")
    ref_token: str = Field(min_length=4, max_length=32)
    fingerprint: str | None = Field(default=None, max_length=64)


@router.post("/attribution/track")
async def attribution_track(
    body: AttributionTrackBody,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
):
    if not x_guest_session:
        raise HTTPException(status_code=400, detail="X-Guest-Session required")
    if not guest_session_trusted(request, x_guest_session):
        raise HTTPException(status_code=403, detail="Guest session validation failed")

    # Установить HttpOnly cookie для защиты guest session от кражи
    from panel_cookies import set_guest_cookie
    set_guest_cookie(response, x_guest_session, request)

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    result = await track_ref_visit(
        ref_kind=body.ref_kind,  # type: ignore[arg-type]
        ref_token=body.ref_token,
        guest_session=x_guest_session,
        fingerprint=body.fingerprint,
        client_ip=ip,
        user_agent=ua,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "invalid"))
    return result


@router.get("/bot-user-avatars/{user_id}")
async def get_bot_user_avatar(user_id: int, access: Optional[str] = None):
    from bot_user_avatars import (
        fetch_and_cache_bot_user_avatar,
        resolve_bot_user_avatar_path,
        verify_bot_user_avatar_access,
    )

    if not verify_bot_user_avatar_access(user_id, access):
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    path = resolve_bot_user_avatar_path(user_id)
    if not path:
        path = await fetch_and_cache_bot_user_avatar(user_id)
    if not path:
        raise HTTPException(
            status_code=404,
            detail="Avatar not found",
            headers={"Cache-Control": "no-store"},
        )
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/casino-avatars/{user_key}")
async def get_casino_player_avatar(user_key: str, access: Optional[str] = None):
    from casino_player_cosmetics import (
        _ALLOWED_EXT,
        parse_signed_user_id,
        resolve_cosmetics_avatar_path,
        verify_cosmetics_avatar_access,
    )

    user_id = parse_signed_user_id(user_key, detail="Avatar not found")
    if not verify_cosmetics_avatar_access(user_id, access):
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    path = resolve_cosmetics_avatar_path(user_id)
    if not path:
        raise HTTPException(
            status_code=404,
            detail="Avatar not found",
            headers={"Cache-Control": "no-store"},
        )
    media = _ALLOWED_EXT.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/casino-idents/{seed}")
async def get_casino_ident_avatar(seed: str):
    from casino_default_avatar import parse_ident_seed, render_ident_svg

    key = parse_ident_seed(seed)
    return Response(
        content=render_ident_svg(key),
        media_type="image/svg+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@router.get("/operator-avatars/{file_id}")
async def get_operator_avatar(file_id: str, access: Optional[str] = None):
    from operator_avatars import (
        resolve_operator_avatar_path,
        verify_operator_avatar_access,
    )

    if not verify_operator_avatar_access(file_id, access):
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    path = resolve_operator_avatar_path(file_id)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    media = {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)


async def _issue_human_check(
    request: Request,
    response: Response,
    x_guest_session: str | None,
):
    from math_captcha import generate_captcha

    ip_address = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # Challenge и HttpOnly cookie выдаются вместе: последующая проверка сможет
    # надёжно связать CAPTCHA с тем же браузером.
    if x_guest_session:
        from panel_cookies import set_guest_cookie

        set_guest_cookie(response, x_guest_session, request)

    return await generate_captcha(
        guest_session=x_guest_session,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.get("/captcha")
async def get_captcha(
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
):
    """Математическая капча: возвращает картинку и challenge_id."""
    return await _issue_human_check(request, response, x_guest_session)


@router.get("/human-check")
async def get_human_check(
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
):
    """Тот же challenge, путь без слова captcha — фильтры рекламы его часто режут."""
    return await _issue_human_check(request, response, x_guest_session)


@router.get("/reviews")
async def get_reviews(limit: int = 12):
    """
    Отзывы из Telegram-канала @focuspayr (синхронизация с t.me/s/focuspayr).
    """
    channel = (settings.reviews_channel_username or "focuspayr").lstrip("@")
    await sync_reviews_from_public_channel()
    items = await list_reviews(limit=min(max(limit, 1), 50))
    return {
        "channel": channel,
        "channel_url": f"https://t.me/{channel}",
        "reviews": items,
    }
