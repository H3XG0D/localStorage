# services/rates_api.py

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import time
from pathlib import Path

import aiohttp

from .runtime_settings import buy_markup, sell_discount

logger = logging.getLogger("rates_api")
logger.setLevel(logging.INFO)

RAPIRA_RATES_URL = "https://api.rapira.net/open/market/rates"
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
RAPIRA_DEBUG_LOG = False  # временно: логировать сырой ответ Rapira
RAPIRA_ATTEMPTS = 4
RAPIRA_RETRY_SLEEP_SEC = 1.0
RAPIRA_REQUEST_TIMEOUT_SEC = 15.0
RAPIRA_FAST_TIMEOUT_SEC = 3.0
RAPIRA_FAST_ATTEMPTS = 1
RAPIRA_BACKOFF_AFTER_FAILS = 2
RAPIRA_BACKOFF_SEC = 300.0
RAPIRA_BACKOFF_CAP_SEC = 900.0

# Крипты, которые поддерживаем (ключи CACHE и PRICING)
SUPPORTED_CRYPTO = ("btc", "usdt", "trx", "ltc")

CACHE: dict = {}
CACHE_TTL = 60  # секунд
USDT_EARN_PAD = 2.0
FROZEN_USDT_PAD = 0.5
_FROZEN: dict = {}
_NEED: dict = {}
_NEED_TTL = 60
_NEED_FAIL_TTL = 20
_need_fail_ts = 0.0
_LAST_SOURCE = "none"
_SNAPSHOT_PATH_OVERRIDE: Path | None = None
_ROOT = Path(__file__).resolve().parents[1]
_rapira_fail_count = 0
_rapira_backoff_until = 0.0
_rapira_backoff_sec = RAPIRA_BACKOFF_SEC
_fetch_lock: asyncio.Lock | None = None
_inflight: asyncio.Task | None = None
# Shared keepalive session: Rapira SYN-drops a large share of NEW connections
# from prod IP, while reused connections are stable.
_rapira_connector: aiohttp.TCPConnector | None = None
_rapira_session: aiohttp.ClientSession | None = None


def _get_rapira_connector() -> aiohttp.TCPConnector:
    global _rapira_connector
    if _rapira_connector is None or _rapira_connector.closed:
        _rapira_connector = aiohttp.TCPConnector(
            limit=5,
            limit_per_host=2,
            ttl_dns_cache=300,
            family=socket.AF_INET,
            keepalive_timeout=60,
        )
    return _rapira_connector


async def _get_rapira_session() -> aiohttp.ClientSession:
    global _rapira_session
    if _rapira_session is None or _rapira_session.closed:
        _rapira_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20, connect=10),
            connector=_get_rapira_connector(),
        )
    return _rapira_session


async def _close_rapira_session() -> None:
    global _rapira_session, _rapira_connector
    if _rapira_session is not None:
        try:
            await _rapira_session.close()
        except Exception:
            pass
        _rapira_session = None
    if _rapira_connector is not None:
        try:
            await _rapira_connector.close()
        except Exception:
            pass
        _rapira_connector = None

USER_RATES_UNAVAILABLE = (
    "Курсы временно недоступны.\nПопробуйте через несколько секунд."
)
USER_NEED_RATES_UNAVAILABLE = (
    "⚠️ Курс CoinGecko временно недоступен. Попробуйте позже."
)

_SECRET_RE = re.compile(
    r"(?i)(token|key|secret|password|bearer|authorization|api[_-]?key)\s*[=:]\s*\S+"
)
_URL_RE = re.compile(r"https?://[^\s]+")


class RatesUnavailableError(Exception):
    """Нет живых курсов Rapira и нет валидного frozen snapshot."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def snapshot_file() -> Path:
    if _SNAPSHOT_PATH_OVERRIDE is not None:
        return _SNAPSHOT_PATH_OVERRIDE
    explicit = (os.getenv("RAPIRA_RATES_SNAPSHOT_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    prod = Path("/opt/tg_bot_btc/data/rapira_rates_snapshot.json")
    if prod.parent.exists():
        return prod
    return _ROOT / "data" / "rapira_rates_snapshot.json"


def reset_rates_state(*, snapshot_path: Path | None = None, clear_file: bool = True) -> None:
    CACHE.clear()
    _FROZEN.clear()
    _NEED.clear()
    global _LAST_SOURCE, _SNAPSHOT_PATH_OVERRIDE, _need_fail_ts
    global _rapira_fail_count, _rapira_backoff_until, _rapira_backoff_sec
    global _fetch_lock, _inflight
    _LAST_SOURCE = "none"
    _need_fail_ts = 0.0
    _rapira_fail_count = 0
    _rapira_backoff_until = 0.0
    _rapira_backoff_sec = RAPIRA_BACKOFF_SEC
    _fetch_lock = None
    _inflight = None
    if snapshot_path is not None:
        _SNAPSHOT_PATH_OVERRIDE = snapshot_path
    if clear_file:
        try:
            snapshot_file().unlink(missing_ok=True)
        except OSError:
            pass


def _sanitize_reason(text: str, limit: int = 160) -> str:
    raw = _SECRET_RE.sub(r"\1=***", str(text or ""))
    raw = _URL_RE.sub("[url]", raw)
    return raw.replace("\n", " ").strip()[:limit]


def _log_reason(prefix: str, exc: BaseException | None = None, extra: str = "") -> str:
    parts = [prefix]
    if extra:
        parts.append(_sanitize_reason(extra, 120))
    if exc is not None:
        parts.append(type(exc).__name__)
        parts.append(_sanitize_reason(str(exc)))
    reason = " | ".join(p for p in parts if p)
    logger.error(reason)
    return reason


def _positive_rates(rates: dict | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for coin in SUPPORTED_CRYPTO:
        raw = (rates or {}).get(coin)
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price > 0:
            out[coin] = price
    return out


def _is_complete_rates(rates: dict | None) -> bool:
    live = _positive_rates(rates)
    return all(coin in live for coin in SUPPORTED_CRYPTO)


def _shift_usdt(rates: dict[str, float] | None, delta: float) -> dict[str, float]:
    out = dict(rates or {})
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
    src = _LAST_SOURCE if source is None else source
    delta = USDT_EARN_PAD
    if src == "frozen":
        delta += FROZEN_USDT_PAD
    return delta


def _with_buy_usdt_pad(rates: dict[str, float] | None, *, source: str | None = None) -> dict[str, float]:
    """USDT serve pad for BUY. Cache and snapshot stay raw."""
    return _shift_usdt(rates, _buy_usdt_delta(source=source))


def _with_frozen_usdt_pad(rates: dict[str, float] | None, *, source: str | None = None) -> dict[str, float]:
    return _with_buy_usdt_pad(rates, source=source)


def _served_price(crypto: str, price: float, *, source: str | None = None) -> float:
    if (crypto or "").lower() != "usdt":
        return float(price)
    return float(price) + _buy_usdt_delta(source=source)


def get_cached_buy_market(crypto: str) -> float | None:
    """Rapira BUY market as served to clients. Cache and snapshot stay raw."""
    base = str(crypto or "").split("_")[0].lower()
    raw = (CACHE.get(base) or {}).get("price")
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return _served_price(base, price)


def _sell_served_price(crypto: str, price: float) -> float:
    raw = float(price)
    if (crypto or "").lower() != "usdt":
        return raw
    shifted = raw - USDT_EARN_PAD
    return shifted if shifted > 0 else raw


def _store_frozen(rates: dict[str, float], ts: float, *, persist: bool = False) -> None:
    _FROZEN.clear()
    for coin in SUPPORTED_CRYPTO:
        _FROZEN[coin] = float(rates[coin])
    _FROZEN["_ts"] = float(ts)
    _FROZEN["_source"] = "rapira"
    if persist:
        _persist_rapira_snapshot(rates, ts)


def _write_cache(rates: dict[str, float], now: float) -> None:
    for coin, price in rates.items():
        if coin in SUPPORTED_CRYPTO and float(price) > 0:
            CACHE[coin] = {"price": float(price), "time": now}


def _memory_frozen() -> dict[str, float] | None:
    rates = _positive_rates(_FROZEN)
    if not _is_complete_rates(rates):
        return None
    return rates


def _persist_rapira_snapshot(rates: dict[str, float], ts: float) -> None:
    path = snapshot_file()
    payload = {
        "source": "rapira",
        "ts": float(ts),
        "rates": {coin: float(rates[coin]) for coin in SUPPORTED_CRYPTO},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        _log_reason("failed to persist Rapira snapshot", e)


def _load_persisted_rapira() -> tuple[dict[str, float], float] | None:
    path = snapshot_file()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _log_reason("failed to read Rapira snapshot", e)
        return None
    if str(raw.get("source") or "") != "rapira":
        return None
    try:
        ts = float(raw.get("ts") or 0)
    except (TypeError, ValueError):
        return None
    rates = _positive_rates(raw.get("rates") if isinstance(raw.get("rates"), dict) else raw)
    if ts <= 0 or not _is_complete_rates(rates):
        return None
    return rates, ts


def get_frozen_snapshot(now: float | None = None) -> dict[str, float] | None:
    """Последний полный курс Rapira: память, затем файл, затем полный CACHE."""
    snap = _memory_frozen()
    if snap:
        return snap
    loaded = _load_persisted_rapira()
    if loaded:
        rates, ts = loaded
        _store_frozen(rates, ts, persist=False)
        logger.warning("Loaded persisted Rapira snapshot ts=%s", int(ts))
        return rates
    rates: dict[str, float] = {}
    oldest: float | None = None
    for coin in SUPPORTED_CRYPTO:
        item = CACHE.get(coin) or {}
        try:
            price = float(item.get("price"))
            ts = float(item.get("time") or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0 or ts <= 0:
            return None
        rates[coin] = price
        oldest = ts if oldest is None else min(oldest, ts)
    if oldest is None:
        return None
    _store_frozen(rates, oldest, persist=False)
    return rates


def parse_rapira_payload(body) -> dict[str, float]:
    """Разбор тела Rapira. Пустой/битый ответ — ошибка; частичный — без выдуманных пар."""
    if not isinstance(body, dict):
        raise ValueError("Rapira response is not an object")
    data = body.get("data")
    if not isinstance(data, list):
        raise ValueError("Rapira response has no data array")
    if not data:
        raise ValueError("empty Rapira data")
    return _parse_rapira_rates(data)


def _parse_rapira_rates(data: list) -> dict[str, float]:
    """
    Парсит ответ Rapira (поле data — массив тикеров).
    Возвращает { "btc": rub, "usdt": rub, "trx": rub, "ltc": rub } — без отсутствующих пар.
    USDT/RUB — прямая котировка; BTC/LTC/TRX через XXX/USDT * USDT/RUB.
    """
    by_symbol = {}
    for item in data:
        sym = (item or {}).get("symbol")
        if sym:
            by_symbol[sym] = item

    usdt_rub = None
    u = by_symbol.get("USDT/RUB")
    if u is not None and "close" in u:
        try:
            usdt_rub = float(u["close"])
        except (TypeError, ValueError):
            usdt_rub = None

    if usdt_rub is None or usdt_rub <= 0:
        raise ValueError("USDT/RUB not found or invalid in Rapira response")

    result = {"usdt": usdt_rub}

    for pair, key in (
        ("BTC/USDT", "btc"),
        ("LTC/USDT", "ltc"),
        ("TRX/USDT", "trx"),
    ):
        ticker = by_symbol.get(pair)
        if ticker is None or "close" not in ticker:
            logger.warning("%s not found in Rapira response (skip)", pair)
            continue
        try:
            rate_usdt = float(ticker["close"])
        except (TypeError, ValueError):
            logger.warning("%s close is not a number (skip)", pair)
            continue
        if rate_usdt <= 0:
            logger.warning("%s close <= 0 (skip)", pair)
            continue
        result[key] = rate_usdt * usdt_rub

    return result


async def _apply_coingecko_fallbacks(
    session: aiohttp.ClientSession,
    rates: dict[str, float],
) -> None:
    """BTC/LTC/TRX в RUB через CoinGecko (USD), если Rapira не отдаёт XXX/USDT."""
    usdt_rub = rates.get("usdt")
    if not usdt_rub or usdt_rub <= 0:
        logger.error("CoinGecko fallback: нет USDT/RUB из Rapira")
        return

    missing = [k for k in COINGECKO_IDS if k not in rates]
    if not missing:
        return

    try:
        async with session.get(
            COINGECKO_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.error("CoinGecko HTTP %s", resp.status)
                return
            body = await resp.json()
            for key, cg_id in COINGECKO_IDS.items():
                if key in rates:
                    continue
                usd = float((body or {}).get(cg_id, {}).get("usd") or 0)
                if usd <= 0:
                    logger.warning("CoinGecko: нет цены для %s", key)
                    continue
                rates[key] = usd * usdt_rub
                logger.info(
                    "%s/RUB через CoinGecko: %g USD × %.2f = %.2f ₽",
                    key.upper(),
                    usd,
                    usdt_rub,
                    rates[key],
                )
    except Exception as e:
        _log_reason("CoinGecko fallback failed", e)


def parse_coingecko_rub(body) -> dict[str, float]:
    """Разбор simple/price CoinGecko (RUB). Частичный ответ — без выдуманных монет."""
    if not isinstance(body, dict):
        raise ValueError("CoinGecko response is not an object")
    out: dict[str, float] = {}
    for key, cg_id in COINGECKO_RUB_IDS.items():
        try:
            rub = float((body.get(cg_id) or {}).get("rub") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if rub > 0:
            out[key] = rub
    return out


def _need_rates_only() -> dict[str, float]:
    return _positive_rates(_NEED)


def _store_need(rates: dict[str, float], ts: float) -> None:
    _NEED.clear()
    _NEED["_ts"] = float(ts)
    for coin, price in rates.items():
        if coin in SUPPORTED_CRYPTO and float(price) > 0:
            _NEED[coin] = float(price)


def _need_is_fresh(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    ts = float(_NEED.get("_ts") or 0)
    if ts <= 0 or now - ts >= _NEED_TTL:
        return False
    return all(coin in _NEED and float(_NEED[coin]) > 0 for coin in SUPPORTED_CRYPTO)


async def fetch_coingecko_rub() -> dict[str, float]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(COINGECKO_RUB_URL) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CoinGecko HTTP {resp.status}")
            body = await resp.json()
    return parse_coingecko_rub(body)


async def get_need_rates_cached() -> dict[str, float]:
    """CoinGecko RUB for BUY+RUB quotes. Does not replace Rapira CACHE."""
    global _need_fail_ts
    now = time.time()
    if _need_is_fresh(now):
        return _need_rates_only()
    stale = _need_rates_only()
    if _need_fail_ts and now - _need_fail_ts < _NEED_FAIL_TTL:
        return stale
    fetched: dict[str, float] = {}
    try:
        fetched = _positive_rates(await fetch_coingecko_rub())
    except Exception as e:
        _need_fail_ts = now
        _log_reason("CoinGecko RUB fetch failed", e)
    if fetched and all(coin in fetched for coin in SUPPORTED_CRYPTO):
        _store_need(fetched, now)
        _need_fail_ts = 0.0
        return fetched
    if all(coin in stale for coin in SUPPORTED_CRYPTO):
        logger.warning("Using stale CoinGecko RUB rates")
        return stale
    if fetched:
        _store_need(fetched, now)
        return fetched
    _need_fail_ts = now
    return stale


async def get_need_price(crypto: str) -> float | None:
    crypto = (crypto or "").lower()
    rates = await get_need_rates_cached()
    try:
        price = float(rates.get(crypto) or 0)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _rapira_fetch_params(*, has_snapshot: bool) -> tuple[float, int]:
    if has_snapshot:
        return RAPIRA_FAST_TIMEOUT_SEC, RAPIRA_FAST_ATTEMPTS
    return RAPIRA_REQUEST_TIMEOUT_SEC, RAPIRA_ATTEMPTS


async def fetch_all_rates_from_rapira(*, has_snapshot: bool = False) -> dict[str, float]:
    """Один запрос к Rapira, возвращает рыночные RUB (возможно частично).

    Shared keepalive session: провайдер режет новые TCP-коннекты,
    переиспользованные соединения стабильны.
    """
    last_error: BaseException | None = None
    timeout_sec, attempts = _rapira_fetch_params(has_snapshot=has_snapshot)
    for attempt in range(attempts):
        try:
            session = await _get_rapira_session()
            async with session.get(RAPIRA_RATES_URL, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as resp:
                if resp.status != 200:
                    last_error = RuntimeError(f"Rapira HTTP {resp.status}")
                    logger.error(
                        "Rapira HTTP %s, attempt %s/%s",
                        resp.status,
                        attempt + 1,
                        attempts,
                    )
                    if attempt + 1 < attempts:
                        await asyncio.sleep(RAPIRA_RETRY_SLEEP_SEC)
                    continue

                body = await asyncio.wait_for(resp.json(), timeout=10)
                if RAPIRA_DEBUG_LOG:
                    data_preview = (body or {}).get("data")
                    symbols = []
                    if isinstance(data_preview, list):
                        for item in data_preview[:20]:
                            sym = (item or {}).get("symbol")
                            if sym:
                                symbols.append(sym)
                    logger.info("[RAPIRA RAW] symbols: %s", symbols)

                rates = parse_rapira_payload(body)
                await _apply_coingecko_fallbacks(session, rates)
                return rates

        except (aiohttp.ServerDisconnectedError, aiohttp.ClientConnectionError) as e:
            last_error = e
            logger.warning("Rapira connection lost, rebuilding session (attempt %s/%s)", attempt + 1, attempts)
            await _close_rapira_session()
            if attempt + 1 < attempts:
                await asyncio.sleep(RAPIRA_RETRY_SLEEP_SEC)
        except asyncio.TimeoutError as e:
            last_error = e
            logger.error(
                "Rapira timeout, attempt %s/%s",
                attempt + 1,
                attempts,
            )
            if attempt + 1 < attempts:
                await asyncio.sleep(RAPIRA_RETRY_SLEEP_SEC)
        except Exception as e:
                last_error = e
                _log_reason(
                    f"Rapira fetch error attempt {attempt + 1}/{attempts}",
                    e,
                )
                if attempt + 1 < attempts:
                    await asyncio.sleep(RAPIRA_RETRY_SLEEP_SEC)

    raise RatesUnavailableError(
        _log_reason("Failed to fetch rates from Rapira after retries", last_error)
    )


def _merge_missing(
    live: dict[str, float],
    frozen: dict[str, float] | None,
) -> tuple[dict[str, float], list[str]]:
    merged = dict(live)
    filled: list[str] = []
    if not frozen:
        return merged, filled
    for coin in SUPPORTED_CRYPTO:
        if coin not in merged and coin in frozen:
            merged[coin] = frozen[coin]
            filled.append(coin)
    return merged, filled


async def refresh_all_rates_cache() -> dict[str, float]:
    """Rapira (+ CoinGecko) → CACHE. При сбое — валидный frozen snapshot.

    Один in-flight fetch на процесс. После серии ошибок — backoff без сети.
    """
    global _inflight
    async with _get_fetch_lock():
        task = _inflight
        if task is None or task.done():
            task = asyncio.create_task(_refresh_all_rates_cache_body())
            _inflight = task
    return await asyncio.shield(task)


def _get_fetch_lock() -> asyncio.Lock:
    global _fetch_lock
    if _fetch_lock is None:
        _fetch_lock = asyncio.Lock()
    return _fetch_lock


def _complete_cache_prices() -> dict[str, float] | None:
    out: dict[str, float] = {}
    for coin in SUPPORTED_CRYPTO:
        item = CACHE.get(coin) or {}
        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        out[coin] = price
    return out


def _serve_local_rates() -> dict[str, float] | None:
    """CACHE (даже просроченный) или frozen — без сети."""
    global _LAST_SOURCE
    cached = _complete_cache_prices()
    if cached is not None:
        return _with_buy_usdt_pad(cached)
    frozen = get_frozen_snapshot()
    if not frozen:
        return None
    _write_cache(frozen, time.time())
    if _LAST_SOURCE == "none":
        _LAST_SOURCE = "frozen"
    return _with_buy_usdt_pad(frozen, source="frozen")


def _note_rapira_success() -> None:
    global _rapira_fail_count, _rapira_backoff_until, _rapira_backoff_sec
    _rapira_fail_count = 0
    _rapira_backoff_until = 0.0
    _rapira_backoff_sec = RAPIRA_BACKOFF_SEC


def _note_rapira_failure(now: float) -> None:
    global _rapira_fail_count, _rapira_backoff_until, _rapira_backoff_sec
    _rapira_fail_count += 1
    if _rapira_fail_count < RAPIRA_BACKOFF_AFTER_FAILS:
        return
    _rapira_backoff_until = now + _rapira_backoff_sec
    logger.warning(
        "Rapira backoff %.0fs after %s consecutive failures",
        _rapira_backoff_sec,
        _rapira_fail_count,
    )
    _rapira_backoff_sec = min(RAPIRA_BACKOFF_CAP_SEC, _rapira_backoff_sec * 2)


def _apply_frozen_fallback(
    frozen: dict[str, float],
    now: float,
    fetch_error: BaseException | None,
    *,
    skipped_live: bool,
) -> dict[str, float]:
    global _LAST_SOURCE
    age = int(now - float(_FROZEN.get("_ts") or now))
    if skipped_live:
        logger.info("Rapira backoff active, using snapshot age_sec=%s", age)
    else:
        _log_reason(
            "Rapira fetch failed, using last Rapira snapshot",
            fetch_error,
            extra=f"age_sec={age}",
        )
    _write_cache(frozen, now)
    _LAST_SOURCE = "frozen"
    return _with_buy_usdt_pad(frozen)


async def _refresh_all_rates_cache_body() -> dict[str, float]:
    """Rapira (+ CoinGecko) → CACHE. При сбое — валидный frozen snapshot."""
    global _LAST_SOURCE
    now = time.time()
    frozen = get_frozen_snapshot(now)
    skip_live = frozen is not None and _rapira_backoff_until > now
    live: dict[str, float] | None = None
    fetch_error: BaseException | None = None
    if not skip_live:
        try:
            live = _positive_rates(
                await fetch_all_rates_from_rapira(has_snapshot=bool(frozen))
            )
            _note_rapira_success()
        except Exception as e:
            fetch_error = e
            _note_rapira_failure(now)

    if live:
        if _is_complete_rates(live):
            _write_cache(live, now)
            _store_frozen(live, now, persist=True)
            _LAST_SOURCE = "rapira"
            return _with_buy_usdt_pad(live)

        missing = [c for c in SUPPORTED_CRYPTO if c not in live]
        logger.warning("Partial Rapira rates, missing=%s", ",".join(missing))
        merged, filled = _merge_missing(live, frozen)
        if _is_complete_rates(merged):
            _write_cache(merged, now)
            _LAST_SOURCE = "partial_frozen"
            logger.warning(
                "Filled partial Rapira from frozen snapshot: %s",
                ",".join(filled),
            )
            return _with_buy_usdt_pad(merged)

        _write_cache(live, now)
        _LAST_SOURCE = "partial"
        if not frozen:
            _log_reason(
                "partial Rapira without valid frozen snapshot",
                extra=f"have={','.join(sorted(live))} missing={','.join(missing)}",
            )
        return _with_buy_usdt_pad(live)

    if frozen:
        return _apply_frozen_fallback(
            frozen, now, fetch_error, skipped_live=skip_live
        )

    _LAST_SOURCE = "none"
    raise RatesUnavailableError(
        _log_reason("Rapira fetch failed, no valid frozen snapshot", fetch_error)
    )


def _is_rapira_cache_fresh() -> bool:
    """Все поддерживаемые крипты в кеше и не просрочены."""
    now = time.time()
    for c in SUPPORTED_CRYPTO:
        if c not in CACHE or now - CACHE[c].get("time", 0) >= CACHE_TTL:
            return False
    return True


async def ensure_rates_cache() -> dict[str, float]:
    """Для пользователя: CACHE/frozen сразу. Сеть — только холодный старт."""
    if _is_rapira_cache_fresh():
        return _with_buy_usdt_pad({c: CACHE[c]["price"] for c in SUPPORTED_CRYPTO})
    local = _serve_local_rates()
    if local is not None:
        return local
    return await refresh_all_rates_cache()


async def get_market_price(crypto: str):
    """
    Возвращает (price, is_stale, is_blocked).
    Курсы берутся из Rapira (один запрос на все пары), кеш общий на 60 сек.
    is_blocked=True только если курс недоступен (нет данных).
    """
    crypto = crypto.lower()
    if crypto not in SUPPORTED_CRYPTO:
        raise ValueError("Unknown crypto")

    now = time.time()

    if crypto in CACHE and now - CACHE[crypto].get("time", 0) < CACHE_TTL:
        price = CACHE[crypto]["price"]
        return _served_price(crypto, price), False, False

    try:
        rates = await ensure_rates_cache()
        price = rates.get(crypto)
        if price is None:
            raw = (CACHE.get(crypto) or {}).get("price")
            if raw is not None:
                price = _served_price(crypto, raw)
        if price is None:
            logger.critical(
                "CRITICAL: No rate for %s after Rapira/frozen fallback", crypto
            )
            return None, True, True
        return price, _LAST_SOURCE != "rapira", False

    except RatesUnavailableError as e:
        logger.error("get_market_price %s unavailable: %s", crypto, e.reason)
        return None, True, True
    except Exception as e:
        _log_reason(f"get_market_price {crypto}", e)
        frozen = get_frozen_snapshot()
        if frozen and crypto in frozen:
            logger.warning("Using frozen snapshot for %s after unexpected error", crypto)
            padded = _with_buy_usdt_pad({crypto: frozen[crypto]}, source="frozen")
            return padded[crypto], True, False
        logger.critical("CRITICAL: No cached price for %s, Rapira unreachable", crypto)
        return None, True, True


def get_sell_market_price(crypto: str):
    """CoinGecko RUB if cached, else raw Rapira. USDT shifted on serve."""
    crypto = crypto.lower()
    need = _need_rates_only().get(crypto)
    try:
        if need and float(need) > 0:
            return _sell_served_price(crypto, need)
    except (TypeError, ValueError):
        pass
    data = CACHE.get(crypto)
    if not data:
        return None
    return _sell_served_price(crypto, data["price"])


def get_cached_rate(crypto: str, direction: str):
    """
    Возвращает курс с учётом наценки / скидки из PRICING на основе CACHE.
    buy = Rapira × buy_markup (по умолчанию +20%).
    sell = CoinGecko (Rapira fallback) × sell_multiplier.
    Если данных нет — возвращает None.
    """
    crypto = crypto.lower()
    if direction == "buy":
        data = CACHE.get(crypto)
        if not data:
            return None
        price = _served_price(crypto, data["price"])
        return price * buy_markup(manual=False)
    price = get_sell_market_price(crypto)
    if price is None:
        return None
    return price * sell_discount()


def has_rate_changed(old: float, new: float, tolerance: float = 0.01):
    if old is None or new is None:
        return False
    return abs(old - new) > tolerance
