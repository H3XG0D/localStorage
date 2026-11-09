"""Конфигурация казино-бота."""
import os
from typing import List
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

_STAGING_PRODUCTION_IPS = {"153.80.249.77"}
_STAGING_PLACEHOLDER_MARKERS = ("change_me", "placeholder", "replace_", "example")


def _is_staging_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in _STAGING_PLACEHOLDER_MARKERS)


def _validate_staging_url(name: str, value: str) -> None:
    if _is_staging_placeholder(value):
        raise RuntimeError(f"FATAL: staging {name} must be explicitly configured")

    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise RuntimeError(f"FATAL: staging {name} must be an absolute HTTP URL")
    if host in _STAGING_PRODUCTION_IPS or host == "focuspay.org" or host.endswith(".focuspay.org"):
        raise RuntimeError(f"FATAL: staging {name} must not target a production host")


def validate_staging_config(environ: dict[str, str]) -> None:
    """Reject incomplete or production-directed configuration before staging startup."""
    if environ.get("ENVIRONMENT", "").strip().lower() != "staging":
        return

    required_values = {
        "BOT_TOKEN": environ.get("BOT_TOKEN", ""),
        "FOCUSPAY_API_URL": environ.get("FOCUSPAY_API_URL", ""),
        "FOCUSPAY_INTERNAL_TOKEN": environ.get("FOCUSPAY_INTERNAL_TOKEN", ""),
        "STAGING_INTERNAL_API_SECRET": environ.get("STAGING_INTERNAL_API_SECRET", ""),
        "WEBHOOK_URL": environ.get("WEBHOOK_URL", ""),
    }
    for name, value in required_values.items():
        if _is_staging_placeholder(value):
            raise RuntimeError(f"FATAL: staging {name} must be explicitly configured")

    if environ["FOCUSPAY_INTERNAL_TOKEN"] != environ["STAGING_INTERNAL_API_SECRET"]:
        raise RuntimeError("FATAL: staging internal API secret confirmation failed")
    if int(environ.get("CASINO_EXCHANGER_ID", "0") or 0) <= 0:
        raise RuntimeError("FATAL: staging CASINO_EXCHANGER_ID must be positive")

    bot_username = environ.get("BOT_USERNAME", "").strip().lstrip("@")
    allowed_username = environ.get("CASINO_STAGING_TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    allowed_id = int(environ.get("CASINO_STAGING_TELEGRAM_BOT_ID", "0") or 0)
    if not allowed_username and allowed_id <= 0:
        raise RuntimeError("FATAL: staging Telegram bot allowlist must be configured")
    if allowed_username and bot_username.lower() != allowed_username.lower():
        raise RuntimeError("FATAL: staging Telegram bot username is not allowlisted")

    try:
        game_chat_id = int(environ.get("GAME_CHAT_ID", "0") or 0)
        allowed_chat_id = int(environ.get("ALLOWED_CHAT_ID", "0") or 0)
        admin_ids = [int(item.strip()) for item in environ.get("ADMIN_IDS", "").split(",") if item.strip()]
    except ValueError as exc:
        raise RuntimeError("FATAL: staging casino Telegram IDs must be numeric") from exc
    if game_chat_id >= 0 or allowed_chat_id != game_chat_id or not admin_ids:
        raise RuntimeError("FATAL: staging casino chat/admin allowlist must be configured")

    _validate_staging_url("FOCUSPAY_API_URL", environ["FOCUSPAY_API_URL"])
    _validate_staging_url("WEBHOOK_URL", environ["WEBHOOK_URL"])


validate_staging_config(os.environ)

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "focuscasino_bot")
ENVIRONMENT = os.getenv("ENVIRONMENT", "").strip().lower()


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


CASINO_STAGING_UI_V2 = (
    ENVIRONMENT == "staging"
    and os.getenv("CASINO_STAGING_UI_V2", "").strip().lower() in {"1", "true", "yes", "on"}
)
# Self-serve SBP/card. Staging defaults on; production stays off unless explicitly enabled.
DEPOSITS_ENABLED = _env_flag("DEPOSITS_ENABLED", default=(ENVIRONMENT == "staging"))

# FocusPay
FOCUSPAY_API_URL = os.getenv("FOCUSPAY_API_URL", "https://focuspay.org")
FOCUSPAY_INTERNAL_TOKEN = os.getenv("FOCUSPAY_INTERNAL_TOKEN", "")
FOCUSPAY_EXCHANGER_API_KEY = os.getenv("FOCUSPAY_EXCHANGER_API_KEY", "")
FOCUSPAY_EXCHANGER_SECRET = os.getenv("FOCUSPAY_EXCHANGER_SECRET", "")
# Staging tunnel example: http://127.0.0.1:18081/casino/fairness — never production.
CASINO_FAIRNESS_URL = os.getenv("CASINO_FAIRNESS_URL", "").rstrip("/")


def derive_casino_miniapp_url(fairness_url: str = "", explicit: str = "") -> str:
    raw = (explicit or "").strip().rstrip("/")
    if raw:
        return raw
    fairness = (fairness_url or "").strip().rstrip("/")
    suffix = "/casino/fairness"
    if fairness.endswith(suffix):
        return fairness[: -len(suffix)] + "/casino/tg"
    return ""


CASINO_MINIAPP_URL = derive_casino_miniapp_url(
    os.getenv("CASINO_FAIRNESS_URL", ""),
    os.getenv("CASINO_MINIAPP_URL", ""),
)

# Webhook
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://casino.focuspay.org/webhook")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8001"))

# Чаты
GAME_CHAT_ID = int(os.getenv("GAME_CHAT_ID", "0")) if os.getenv("GAME_CHAT_ID") else 0
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0")) if os.getenv("ALLOWED_CHAT_ID") else None  # Чат для PVP игр

# Админы
ADMIN_IDS: List[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
]

# Логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Валюта
CURRENCY = "RUB"
CURRENCY_SYMBOL = "₽"

# Лимиты (будут перезаписаны из casino_settings)
MIN_BET = 10.0
MAX_BET = 100000.0
COMMISSION_RATE = 15.0  # whole percent from backend (15.0 = 15%)
COMMISSION_RATE_WAGERING_ACTIVE = 15.0
COMMISSION_RATE_WAGERING_COMPLETE = 5.0
WAGERING_PERCENT = 21.0
CREATOR_CUT_PERCENT = 5.0  # доля от сформированной комиссии, whole percent
REFERRAL_L1_PERCENT = 2.0  # доля от сформированной комиссии, whole percent
REFERRAL_L2_PERCENT = 2.0  # доля от сформированной комиссии, whole percent

# Игровые лимиты
MAX_ACTIVE_GAMES_PER_USER = 5
GAME_EXPIRATION_HOURS = 2
RAFFLE_SLOTS = 6
RAFFLE_TIMEOUT_HOURS = 3
RAFFLE_ENABLED = False

# Карточные игры
BACCARA_MIN_BET = 30.0
BLACKJACK_MIN_BET = 30.0

# Пополнение баланса: по номиналу (0% комиссии), окно оплаты, выбор способа.
# Наценка на пополнение отключена — клиент платит ровно сумму. Дом получает свою
# долю комиссией с игр: wagering_percent — плюс казино с депозита, не оборот ставок.
DEPOSIT_COMMISSION_PERCENT = float(os.getenv("DEPOSIT_COMMISSION_PERCENT", "0"))
DEPOSIT_MIN_RUB = float(os.getenv("DEPOSIT_MIN_RUB", "500"))
DEPOSIT_MAX_RUB = float(os.getenv("DEPOSIT_MAX_RUB", "100000"))
DEPOSIT_WINDOW_MINUTES = int(os.getenv("DEPOSIT_WINDOW_MINUTES", "15"))
# Способы оплаты: sub_token обменника -> человекочитаемое имя.
DEPOSIT_METHODS = {
    "SBPRUB": "СБП",
    "CARDRUB": "Карта",
}
