# Коэффициенты наценки / скидки
# buy_markup: во сколько раз выше рыночной цены продаём клиенту (RUB → CRYPTO)
# sell_discount: во сколько раз ниже рыночной цены покупаем у клиента (CRYPTO → RUB)
import fcntl
import ipaddress
import json
import os
import sys
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        print(f"FATAL: required environment variable {key} is not set", file=sys.stderr)
        sys.exit(1)
    return value


PRICING = {
    "btc": {
        "buy_markup": 1.20,   # 20% к рынку
        "sell_discount": 0.96 # комиссия клиента 4% от рынка
    },
    "usdt": {
        "buy_markup": 1.20,
        "sell_discount": 0.96
    },
    "trx": {
        "buy_markup": 1.20,
        "sell_discount": 0.96
    },
    "ltc": {
        "buy_markup": 1.20,
        "sell_discount": 0.96
    }
}

_DEFAULT_SELL_WALLETS = {
    "usdt": {"trc20": "", "erc20": "", "bep20": "", "arbitrum": "", "solana": ""},
    "btc": {"mainnet": ""},
    "trx": {"mainnet": ""},
    "ltc": {"mainnet": ""},
}


def _load_sell_wallets() -> dict:
    raw = _env("SELL_WALLETS_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            print("FATAL: SELL_WALLETS_JSON is not valid JSON", file=sys.stderr)
            sys.exit(1)
    return _DEFAULT_SELL_WALLETS


SELL_WALLETS = _load_sell_wallets()


# Лимиты по СУММАМ (в крипте и рублях) для конкретной монеты. Минимум задаётся через min_crypto / min_fiat.
AMOUNT_LIMITS = {
    "btc": {
        "min_crypto": "0.00012",
        "max_crypto": "1.00081882",
        "min_fiat": 1000,
        "max_fiat": 2000000
    },
    "usdt": {
        "min_crypto": "10",
        "max_crypto": "50000",
        "min_fiat": 1000,
        "max_fiat": 3000000
    },
    "trx": {
        "min_crypto": "30",
        "max_crypto": "200000",
        "min_fiat": 1000,
        "max_fiat": 1000000
    },
    "ltc": {
        "min_crypto": "0.1",
        "max_crypto": "500",
        "min_fiat": 1000,
        "max_fiat": 1500000
    }
}

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
# Отдельный бот: модерация focus-чата / отзывов / новостей (polling).
TELEGRAM_ANTISPAM_BOT_TOKEN = _env("TELEGRAM_ANTISPAM_BOT_TOKEN")
# Webhook вместо polling — устраняет Conflict при втором getUpdates (старый prod / dev).
TELEGRAM_WEBHOOK_URL = _env("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_WEBHOOK_PATH = _env("TELEGRAM_WEBHOOK_PATH", "bot/telegram")
TELEGRAM_WEBHOOK_LISTEN = _env("TELEGRAM_WEBHOOK_LISTEN", "127.0.0.1")
TELEGRAM_WEBHOOK_PORT = int(_env("TELEGRAM_WEBHOOK_PORT", "8082") or "8082")
TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET", "")

_admin_group_raw = _env("TELEGRAM_ADMIN_GROUP_ID")
TELEGRAM_ADMIN_GROUP_ID = int(_admin_group_raw) if _admin_group_raw else 0

_owner_group_raw = _env("TELEGRAM_OWNER_GROUP_ID")
TELEGRAM_OWNER_GROUP_ID = int(_owner_group_raw) if _owner_group_raw else 0

# Группа операторов: заявки, чеки, «Выплачено» (не смешивать с админкой владельца).
_ops_group_raw = _env("TELEGRAM_OPS_GROUP_ID", "")
TELEGRAM_OPS_GROUP_ID = int(_ops_group_raw.strip()) if _ops_group_raw.strip() else 0

# Группа отчётов владельца (/dash, /pulse, /post) — может отличаться от ops.
_reports_group_raw = _env("TELEGRAM_REPORTS_GROUP_ID", "")
if _reports_group_raw.strip():
    TELEGRAM_REPORTS_GROUP_ID = int(_reports_group_raw.strip())
elif TELEGRAM_ADMIN_GROUP_ID:
    TELEGRAM_REPORTS_GROUP_ID = TELEGRAM_ADMIN_GROUP_ID
else:
    TELEGRAM_REPORTS_GROUP_ID = TELEGRAM_OWNER_GROUP_ID

# Группа внештатных заявок (кабинет внештатника, appeals PDF/видео/чек).
_external_deals_group_raw = _env("TELEGRAM_EXTERNAL_DEALS_GROUP_ID", "")
TELEGRAM_EXTERNAL_DEALS_GROUP_ID = (
    int(_external_deals_group_raw.strip()) if _external_deals_group_raw.strip() else 0
)

# Группа проверки клиентов (до реквизитов: профиль / совпадение кошелька).
_client_review_group_raw = _env("TELEGRAM_CLIENT_REVIEW_GROUP_ID", "") or _env(
    "CLIENT_REVIEW_GROUP_ID", ""
)
TELEGRAM_CLIENT_REVIEW_GROUP_ID = (
    int(_client_review_group_raw.strip()) if _client_review_group_raw.strip() else 0
)

# Группа споров Payfast / Moonlight (видео-подтверждения оплаты).
_appeals_group_raw = _env("TELEGRAM_APPEALS_GROUP_ID", "")
TELEGRAM_APPEALS_GROUP_ID = int(_appeals_group_raw.strip()) if _appeals_group_raw.strip() else 0

# Общий чат пользователей (focus чат): автоприём заявок на вступление.
_community_chat_raw = _env("TELEGRAM_COMMUNITY_CHAT_ID", "")
TELEGRAM_COMMUNITY_CHAT_ID = (
    int(_community_chat_raw.strip()) if _community_chat_raw.strip() else 0
)

# Новости проекта FocusPay: автоприём заявок на вступление.
_news_chat_raw = _env("TELEGRAM_NEWS_CHAT_ID", "")
TELEGRAM_NEWS_CHAT_ID = int(_news_chat_raw.strip()) if _news_chat_raw.strip() else 0

OWNER_STALE_PAYOUT_MINUTES = int(_env("OWNER_STALE_PAYOUT_MINUTES", "10"))
OWNER_MONITOR_INTERVAL_SEC = int(_env("OWNER_MONITOR_INTERVAL_SEC", "60"))

WEBHOOK_SECRET = _env("WEBHOOK_SECRET", "")
WEBHOOK_ALLOWED_IPS = _env("WEBHOOK_ALLOWED_IPS", "")
WEBHOOK_TRUSTED_PROXIES = _env("WEBHOOK_TRUSTED_PROXIES", "127.0.0.1,::1")
RECEIPT_SECRET = _env("RECEIPT_SECRET", "") or WEBHOOK_SECRET
DATABASE_DSN = _env("DATABASE_DSN")
CALLBACK_SECRET = _env("CALLBACK_SECRET")

_admin_ids_raw = _env("TELEGRAM_ADMIN_IDS", "")
TELEGRAM_ADMIN_IDS = [
    int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()
]

_finance_owner_raw = _env("FINANCE_OWNER_TELEGRAM_ID", "")
FINANCE_OWNER_TELEGRAM_ID = (
    int(_finance_owner_raw.strip())
    if _finance_owner_raw.strip()
    else (TELEGRAM_ADMIN_IDS[0] if TELEGRAM_ADMIN_IDS else 0)
)


def is_finance_owner(user_id: int) -> bool:
    return bool(FINANCE_OWNER_TELEGRAM_ID) and int(user_id) == int(FINANCE_OWNER_TELEGRAM_ID)


def _supergroup_alt_id(chat_id: int) -> int | None:
    """После апгрейда в супергруппу: -123456 -> -100123456 (и обратно)."""
    cid = int(chat_id)
    s = str(cid)
    if s.startswith("-100") and len(s) > 4:
        return int("-" + s[4:])
    if cid < 0 and cid > -1_000_000_000_000:
        return int("-100" + s.lstrip("-"))
    return None


def ops_group_id() -> int:
    """Группа операторов: заявки, чеки, статусы оплаты."""
    if TELEGRAM_OPS_GROUP_ID:
        return int(TELEGRAM_OPS_GROUP_ID)
    from services.ops_group_store import read_ops_group_id

    return read_ops_group_id()


def reports_group_id() -> int:
    """ID группы отчётов владельца и админ-команд в группе."""
    return int(TELEGRAM_REPORTS_GROUP_ID or 0)


def external_deals_group_id() -> int:
    """Группа внештатных заявок: appeals по сделкам кабинета внештатника."""
    if TELEGRAM_EXTERNAL_DEALS_GROUP_ID:
        return int(TELEGRAM_EXTERNAL_DEALS_GROUP_ID)
    from services.external_deals_group_store import read_external_deals_group_id

    return read_external_deals_group_id()


def client_review_group_id() -> int:
    """Группа проверки клиентов до реквизитов (профиль / wallet-reuse)."""
    if TELEGRAM_CLIENT_REVIEW_GROUP_ID:
        return int(TELEGRAM_CLIENT_REVIEW_GROUP_ID)
    from services.client_review_group_store import read_client_review_group_id

    return read_client_review_group_id()


def is_client_review_group_chat(chat_id: int | None) -> bool:
    gid = client_review_group_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (
        alt_cid is not None and alt_cid == gid
    )


def appeals_group_id() -> int:
    """Группа споров: видео-подтверждения оплаты для Payfast."""
    return int(TELEGRAM_APPEALS_GROUP_ID or 0)


def community_chat_id() -> int:
    """Общий чат пользователей (focus чат)."""
    if TELEGRAM_COMMUNITY_CHAT_ID:
        return int(TELEGRAM_COMMUNITY_CHAT_ID)
    from services.community_chat_store import read_community_chat_id

    return read_community_chat_id()


def is_community_chat(chat_id: int | None) -> bool:
    gid = community_chat_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (alt_cid is not None and alt_cid == gid)


def news_chat_id() -> int:
    """Группа/канал новостей проекта FocusPay."""
    if TELEGRAM_NEWS_CHAT_ID:
        return int(TELEGRAM_NEWS_CHAT_ID)
    from services.news_chat_store import read_news_chat_id

    return read_news_chat_id()


def is_news_chat(chat_id: int | None) -> bool:
    gid = news_chat_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (alt_cid is not None and alt_cid == gid)


def is_appeals_group_chat(chat_id: int | None) -> bool:
    gid = appeals_group_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (alt_cid is not None and alt_cid == gid)


def is_ops_group_chat(chat_id: int | None) -> bool:
    gid = ops_group_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (alt_cid is not None and alt_cid == gid)


def is_external_deals_group_chat(chat_id: int | None) -> bool:
    gid = external_deals_group_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (alt_cid is not None and alt_cid == gid)


def is_reports_group_chat(chat_id: int | None) -> bool:
    gid = reports_group_id()
    cid = int(chat_id or 0)
    if not gid or not cid:
        return False
    if cid == gid:
        return True
    alt_gid = _supergroup_alt_id(gid)
    alt_cid = _supergroup_alt_id(cid)
    return (alt_gid is not None and cid == alt_gid) or (alt_cid is not None and alt_cid == gid)


def is_owner_group_chat(chat_id: int | None) -> bool:
    return is_reports_group_chat(chat_id)


def is_owner_user(user_id: int) -> bool:
    return is_finance_owner(user_id)


def is_reports_user(user_id: int, username: str | None = None) -> bool:
    """Who may run /dash /pulse /users /misses in the reports group."""
    uid = int(user_id or 0)
    if not uid:
        return False
    if is_finance_owner(uid) or uid in TELEGRAM_ADMIN_IDS:
        return True
    un = (username or "").strip().lstrip("@").lower()
    extra = {
        x.strip().lstrip("@").lower()
        for x in _env("TELEGRAM_REPORTS_USERNAMES", "").split(",")
        if x.strip()
    }
    return bool(un and un in extra)


def owner_dashboard_enabled() -> bool:
    return bool(reports_group_id() and FINANCE_OWNER_TELEGRAM_ID)


USER_REFERRAL_PERCENT = float(_env("USER_REFERRAL_PERCENT", "5.0"))
USER_REFERRAL_MIN_WITHDRAW_CARD_RUB = int(
    _env("USER_REFERRAL_MIN_WITHDRAW_CARD_RUB", "20000")
)
CASINO_MIN_WITHDRAW_CARD_RUB = int(_env("CASINO_MIN_WITHDRAW_CARD_RUB", "20000"))
CASINO_WITHDRAW_FEE_CARD_RUB = float(_env("CASINO_WITHDRAW_FEE_CARD_RUB", "100"))
CASINO_WITHDRAW_FEE_USD_BTC = float(_env("CASINO_WITHDRAW_FEE_USD_BTC", "2.5"))
CASINO_WITHDRAW_FEE_USD_LTC = float(_env("CASINO_WITHDRAW_FEE_USD_LTC", "2.5"))
CASINO_WITHDRAW_FEE_USD_TRX = float(_env("CASINO_WITHDRAW_FEE_USD_TRX", "2.5"))
USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD = float(
    _env("USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD", "10")
)
USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_BTC = float(
    _env("USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_BTC", "5")
)
USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_LTC = float(
    _env("USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_LTC", "5")
)
USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_TRX = float(
    _env("USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_TRX", "5")
)
USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_USDT = float(
    _env("USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_USDT", "20")
)

# Исходящая сеть: карта и BTC/LTC/TRX — CASINO_WITHDRAW_FEE_*; USDT — $ ниже.
# CRYPTO_NETWORK_FEE_RUB_* в .env больше не читаются (не должны перебивать таблицу).
CRYPTO_NETWORK_FEE_USD_USDT = float(_env("CRYPTO_NETWORK_FEE_USD_USDT", "4"))

# Покупка BTC: до этой ставки отправку оплачивает компания, превышение идёт в счёт клиенту.
BUY_BTC_FEE_FREE_SAT_VB = float(_env("BUY_BTC_FEE_FREE_SAT_VB", "2"))
# Запас с учётом нескольких входов: TYPICAL_VSIZE=141 — это оптимистичный один вход.
BUY_BTC_FEE_VSIZE = int(_env("BUY_BTC_FEE_VSIZE", "200"))
# Ставка может вырасти между выдачей реквизитов и отправкой — разницу ест компания.
BUY_BTC_FEE_BUFFER_PCT = float(_env("BUY_BTC_FEE_BUFFER_PCT", "20"))
# Потолок наценки от суммы заявки: на мелком обмене сетевая комиссия иначе душит конверсию.
BUY_BTC_FEE_MAX_PCT_OF_ORDER = float(_env("BUY_BTC_FEE_MAX_PCT_OF_ORDER", "3"))

SELL_ATM_COMMISSION_PCT = float(_env("SELL_ATM_COMMISSION_PCT", "7"))

MERCHANT_PAYIN_LIMITS = {
    "SBPRUB": {"max_single": 150000, "min_single": 1000},
    "CARDRUB": {"max_single": 150000, "min_single": 1000},
}
OPERATOR_FALLBACK_MIN_RUB = int(_env("OPERATOR_FALLBACK_MIN_RUB", "1000"))
CARD_FEE_AUTO = float(_env("CARD_FEE_AUTO", "0.12"))    # комиссия провайдера карт (авто-бот)
CARD_FEE_MANUAL = float(_env("CARD_FEE_MANUAL", "0.14"))  # комиссия провайдера карт (ручные)
BUY_SPREAD = float(_env("BUY_SPREAD", "0.20"))             # спред в цене (buy_markup=1.20)

USER_CASHBACK_PERCENT = float(_env("USER_CASHBACK_PERCENT", "5.0"))
USER_CASHBACK_TIER_STEP_PERCENT = float(_env("USER_CASHBACK_TIER_STEP_PERCENT", "2.0"))
USER_CASHBACK_TIER_EVERY_N = int(_env("USER_CASHBACK_TIER_EVERY_N", "5"))
USER_CASHBACK_PERCENT_MAX = float(_env("USER_CASHBACK_PERCENT_MAX", "15.0"))
MAX_PAYIN_CHAIN_PARTS = int(_env("MAX_PAYIN_CHAIN_PARTS", "3"))
EXPIRE_GRACE_SECONDS = int(_env("EXPIRE_GRACE_SECONDS", "120"))
# Сколько ждём чек/видео от клиента, прежде чем истечь заявку в AWAITING_CHECK.
RECEIPT_WAIT_WINDOW_MINUTES = int(_env("RECEIPT_WAIT_WINDOW_MINUTES", "1440"))
# Сколько держим «чек на проверке у оператора», прежде чем экспайрер
# сверится с Payfast / ручной выплатой. Без потолка заявка жила неделями.
RECEIPT_OPS_PENDING_MAX_MINUTES = int(_env("RECEIPT_OPS_PENDING_MAX_MINUTES", "120"))
DB_POOL_MIN = int(_env("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(_env("DB_POOL_MAX", "10"))

_merchant_json = _env("MERCHANT_JSON", "")
if _merchant_json:
    MERCHANT = json.loads(_merchant_json)
else:
    MERCHANT = {
        "base_url": _env("MERCHANT_BASE_URL", "https://payfast.website/api_merchant"),
        "api_key": _env("MERCHANT_API_KEY", ""),
        "secret_key": _env("MERCHANT_SECRET_KEY", ""),
        "callback_url": _env("MERCHANT_CALLBACK_URL", ""),
        "sub_token": _env("MERCHANT_SUB_TOKEN", "CARDRUB"),
        "merchant_id": _env("MERCHANT_ID", "") or _env("PAYFAST_MERCHANT_ID", ""),
    }

# finance666: выплаты по QR СБП с мерчантского USDT-баланса.
FINANCE666_BASE_URL = _env("FINANCE666_BASE_URL", "https://api.finance666.com").rstrip("/")
FINANCE666_API_KEY = _env("FINANCE666_API_KEY", "").strip()
FINANCE666_WEBHOOK_SECRET = _env("FINANCE666_WEBHOOK_SECRET", "").strip()

PUBLIC_SITE_URL = _env("PUBLIC_SITE_URL", "https://focuspay.org")
PUBLIC_ONION_URL = _env("PUBLIC_ONION_URL", "").strip().rstrip("/")
DOLIV_ONION_URL = _env("DOLIV_ONION_URL", "").strip().rstrip("/")

DEFAULT_CASINO_BOT_USERNAME = "focusludka_bot"


def casino_bot_username() -> str:
    """Username игрового бота FocusBet без @. Прод: focusludka_bot."""
    name = (_env("CASINO_BOT_USERNAME", DEFAULT_CASINO_BOT_USERNAME) or "").strip().lstrip("@")
    return name or DEFAULT_CASINO_BOT_USERNAME


def casino_bot_url() -> str:
    return f"https://t.me/{casino_bot_username()}"


DEFAULT_VPN_BOT_USERNAME = "focusvpn1_bot"


def vpn_bot_username() -> str:
    """Username отдельного бота FocusVPN без @ (VPN_BOT_USERNAME)."""
    name = (_env("VPN_BOT_USERNAME", DEFAULT_VPN_BOT_USERNAME) or "").strip().lstrip("@")
    return name or DEFAULT_VPN_BOT_USERNAME


def vpn_bot_url() -> str:
    return f"https://t.me/{vpn_bot_username()}?start=fp"

REVIEW_BONUS_TEXT_RUB = float(_env("REVIEW_BONUS_TEXT_RUB", _env("REVIEW_BONUS_RUB", "50")))
REVIEW_BONUS_PHOTO_RUB = float(_env("REVIEW_BONUS_PHOTO_RUB", "100"))
REVIEW_BONUS_RUB = REVIEW_BONUS_TEXT_RUB  # обратная совместимость
REVIEWS_CHANNEL_USERNAME = _env("REVIEWS_CHANNEL_USERNAME", "focuspayr").lstrip("@")
_reviews_chat = _env("REVIEWS_PUBLISH_CHAT_ID", "").strip()
REVIEWS_PUBLISH_CHAT_ID: int | str | None = None
if _reviews_chat:
    try:
        REVIEWS_PUBLISH_CHAT_ID = int(_reviews_chat)
    except ValueError:
        REVIEWS_PUBLISH_CHAT_ID = _reviews_chat.lstrip("@")
elif REVIEWS_CHANNEL_USERNAME:
    REVIEWS_PUBLISH_CHAT_ID = f"@{REVIEWS_CHANNEL_USERNAME}"


def reviews_channel_url() -> str:
    return f"https://t.me/{REVIEWS_CHANNEL_USERNAME}"


def reviews_chat_id() -> int | str:
    """Канал отзывов для автоприёма заявок: numeric id, иначе @username."""
    from services.reviews_chat_store import read_reviews_chat_id

    stored = read_reviews_chat_id()
    if stored:
        return stored
    if isinstance(REVIEWS_PUBLISH_CHAT_ID, int) and REVIEWS_PUBLISH_CHAT_ID:
        return int(REVIEWS_PUBLISH_CHAT_ID)
    if isinstance(REVIEWS_PUBLISH_CHAT_ID, str) and REVIEWS_PUBLISH_CHAT_ID.strip():
        raw = REVIEWS_PUBLISH_CHAT_ID.strip().lstrip("@")
        if raw.lstrip("-").isdigit():
            return int(raw)
        return f"@{raw}"
    if REVIEWS_CHANNEL_USERNAME:
        return f"@{REVIEWS_CHANNEL_USERNAME.lstrip('@')}"
    return 0


def is_reviews_chat(chat_id: int | None, username: str | None = None) -> bool:
    """Матч канала отзывов по numeric id или @username (focuspayr)."""
    uname = (username or "").lstrip("@").lower()
    expected = (REVIEWS_CHANNEL_USERNAME or "").lstrip("@").lower()
    if uname and expected and uname == expected:
        return True
    gid = reviews_chat_id()
    cid = int(chat_id or 0)
    if isinstance(gid, int) and gid and cid:
        if cid == gid:
            return True
        alt_gid = _supergroup_alt_id(gid)
        alt_cid = _supergroup_alt_id(cid)
        return (alt_gid is not None and cid == alt_gid) or (
            alt_cid is not None and alt_cid == gid
        )
    return False


COMMUNITY_CHAT_URL = _env("COMMUNITY_CHAT_URL", "https://t.me/+It9i6n_8FUgwM2Nl").strip()
NEWS_CHAT_URL = _env("NEWS_CHAT_URL", "").strip()


def community_chat_url() -> str:
    from services.community_chat_store import read_community_invite_link

    stored = read_community_invite_link()
    if stored:
        return stored
    return COMMUNITY_CHAT_URL


def news_chat_url() -> str:
    from services.news_chat_store import read_news_invite_link

    stored = read_news_invite_link()
    if stored:
        return stored
    return NEWS_CHAT_URL


def reviews_site_url() -> str:
    base = PUBLIC_SITE_URL.rstrip("/")
    return f"{base}/#reviews"


def environment() -> str:
    return _env("ENVIRONMENT", "production").strip().lower()


def is_staging() -> bool:
    return environment() == "staging"


def staging_safe_background_tasks_enabled() -> bool:
    return _env("STAGING_ENABLE_SAFE_BACKGROUND_TASKS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def background_tasks_enabled() -> bool:
    """Disable every recurring job by default in staging."""
    return not is_staging() or staging_safe_background_tasks_enabled()


def polling_drops_pending_updates() -> bool:
    """Only staging discards queued Telegram updates from previous runs."""
    return is_staging()


def acquire_staging_polling_lock():
    """Acquire a non-blocking local lock for the staging polling process."""
    if not is_staging():
        return None
    lock_path = _env("STAGING_POLLING_LOCK_PATH", "/tmp/focuspay-staging-bot.polling.lock")
    lock = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print("FATAL: another local staging polling process is already running", file=sys.stderr)
        sys.exit(1)
    return lock


def _normalise_bot_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def _is_safe_staging_endpoint(value: str) -> bool:
    """Allow only local/private or explicitly non-production endpoint hosts."""
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https", "postgres", "postgresql", "postgresql+asyncpg"}
            or not parsed.hostname
        ):
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"postgres", "redis", "backend", "gateway", "fake-payfast", "casino-bot"}:
            return True
        if host == "localhost" or host.endswith(".localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
        except ValueError:
            labels = host.split(".")
            return any(label in {"staging", "stage", "test", "dev"} for label in labels) or host.endswith(".test")
    except ValueError:
        return False


def validate_staging_config(env: dict[str, str] | None = None) -> list[str]:
    """Return staging configuration errors without reading or logging secret values."""
    source = os.environ if env is None else env
    get = lambda key: str(source.get(key, "")).strip()
    errors: list[str] = []

    required = (
        "STAGING_TELEGRAM_BOT_USERNAME",
        "STAGING_TELEGRAM_BOT_ID",
        "TELEGRAM_BOT_USERNAME",
        "TELEGRAM_BOT_ID",
        "TELEGRAM_ADMIN_GROUP_ID",
        "TELEGRAM_OPS_GROUP_ID",
        "TELEGRAM_REPORTS_GROUP_ID",
        "TELEGRAM_EXTERNAL_DEALS_GROUP_ID",
        "TELEGRAM_CLIENT_REVIEW_GROUP_ID",
        "TELEGRAM_APPEALS_GROUP_ID",
        "TELEGRAM_COMMUNITY_CHAT_ID",
        "TELEGRAM_NEWS_CHAT_ID",
        "REVIEWS_PUBLISH_CHAT_ID",
    )
    errors.extend(f"missing {key}" for key in required if not get(key))

    if get("STAGING_TELEGRAM_BOT_USERNAME") and get("TELEGRAM_BOT_USERNAME"):
        if _normalise_bot_username(get("STAGING_TELEGRAM_BOT_USERNAME")) != _normalise_bot_username(get("TELEGRAM_BOT_USERNAME")):
            errors.append("TELEGRAM_BOT_USERNAME does not match STAGING_TELEGRAM_BOT_USERNAME")
    if get("STAGING_TELEGRAM_BOT_ID") and get("TELEGRAM_BOT_ID"):
        if get("STAGING_TELEGRAM_BOT_ID") != get("TELEGRAM_BOT_ID"):
            errors.append("TELEGRAM_BOT_ID does not match STAGING_TELEGRAM_BOT_ID")

    for key in required[4:]:
        value = get(key)
        if value and not value.lstrip("-").isdigit():
            errors.append(f"{key} must be a numeric chat ID")

    endpoint_defaults = {
        "PUBLIC_SITE_URL": "https://focuspay.org",
        "EXCHANGE_API_URL": "http://127.0.0.1:8000",
        "MERCHANT_BASE_URL": "https://payfast.website/api_merchant",
    }
    for key in (
        "PUBLIC_SITE_URL",
        "EXCHANGE_API_URL",
        "MERCHANT_BASE_URL",
        "MERCHANT_CALLBACK_URL",
        "TELEGRAM_WEBHOOK_URL",
        "DATABASE_DSN",
    ):
        value = get(key) or endpoint_defaults.get(key, "")
        if value and not _is_safe_staging_endpoint(value):
            errors.append(f"{key} must use a local, private, or explicitly staging endpoint")
    return errors


def validate_bot_config() -> None:
    """Fail fast if secrets required for the Telegram bot are missing."""
    missing = []
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "DATABASE_DSN",
        "CALLBACK_SECRET",
    ):
        if not _env(key):
            missing.append(key)
    if not TELEGRAM_ADMIN_IDS:
        missing.append("TELEGRAM_ADMIN_IDS")
    if missing:
        print(
            "FATAL: missing required environment variables: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        sys.exit(1)
    if is_staging():
        staging_errors = validate_staging_config()
        if staging_errors:
            print(
                "FATAL: invalid staging configuration: " + "; ".join(staging_errors),
                file=sys.stderr,
            )
            sys.exit(1)


def validate_webhook_config() -> None:
    """Fail fast if secrets required for the webhook server are missing."""
    missing = []
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "DATABASE_DSN",
        "CALLBACK_SECRET",
        "WEBHOOK_SECRET",
    ):
        if not _env(key):
            missing.append(key)
    if missing:
        print(
            "FATAL: missing required environment variables: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        sys.exit(1)
    ips = _env("WEBHOOK_ALLOWED_IPS", "")
    site = (_env("PUBLIC_SITE_URL", "") or "").strip().lower()
    is_prod = site.startswith("https://") and "localhost" not in site
    merchant_key = (MERCHANT.get("api_key") or "").strip()
    if is_prod and not merchant_key:
        print(
            "FATAL: MERCHANT_API_KEY must be set in production (Payfast callback auth)",
            file=sys.stderr,
        )
        sys.exit(1)
    if is_prod and not (MERCHANT.get("merchant_id") or "").strip():
        print(
            "WARN: MERCHANT_ID not set — callback проверяется только по api_key. "
            "Задайте числовой id_merchant из кабинета Payfast.",
            file=sys.stderr,
        )
    if not ips.strip():
        print(
            "WARN: WEBHOOK_ALLOWED_IPS is not set — IP filter disabled, "
            "callbacks authenticated by signature only",
            file=sys.stderr,
        )
    else:
        print(
            "INFO: WEBHOOK_ALLOWED_IPS is set — IP filter enabled for /callback",
            file=sys.stderr,
        )
