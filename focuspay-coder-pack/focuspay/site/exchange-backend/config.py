import json
import os
from functools import cached_property
from typing import List
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    environment: str = ""
    database_dsn: str = "postgresql://exchange_bot:777@127.0.0.1:5432/exchange_bot"
    # Required from env/.env — no hardcoded fallback secret (Bandit B105).
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 240  # 4 hours (prod: override in .env if needed)

    telegram_bot_token: str = ""
    # @focusvpn1_bot. Result of a VPN review is delivered in that chat.
    focusvpn_bot_token: str = ""
    # Shared with the FocusPay bot. Default in code is /var/lib/focuspay/vpn-review-photos.
    vpn_review_photo_dir: str = ""
    telegram_bot_username: str = ""
    chat_support_username: str = "focus_operator"
    # Comma-separated Telegram sticker set names for operator chat picker (getStickerSet)
    operator_sticker_sets: str = ""
    # Admin broadcast sticker sets (CSV). Empty → fall back to operator_sticker_sets.
    broadcast_sticker_sets: str = ""
    # Broadcast AI draft (opt-in). Default OFF — no external calls.
    broadcast_ai_enabled: bool = False
    broadcast_ai_provider_allowlist: str = "openai,openrouter,offline"
    broadcast_ai_model_allowlist: str = ""
    broadcast_ai_model: str = ""  # empty = current Ops AI / Lelouch chat model
    broadcast_ai_timeout_sec: int = 20
    broadcast_ai_max_chars: int = 4096
    telegram_admin_group_id: int = 0
    # Группа операторов (заявки, чеки). Если 0 — используется telegram_admin_group_id.
    telegram_ops_group_id: int = 0
    # Группа внештатных заявок (кабинет внештатника). Если 0 — fallback на ops.
    telegram_external_deals_group_id: int = 0
    # Группа отчётов владельца (выплаты, финансы). Если 0 — telegram_admin_group_id.
    telegram_reports_group_id: int = 0
    # Канал/группа новостей FocusPay. Тот же ID, что TELEGRAM_NEWS_CHAT_ID у бота.
    # 0 — брать последнюю активную строку news_chat_allowlist.
    telegram_news_chat_id: int = 0
    reviews_channel_username: str = "focuspayr"
    public_site_url: str = "http://localhost:5173"
    # Tor v3 mirrors (http://<56chars>.onion). Empty = not published.
    public_onion_url: str = ""
    doliv_onion_url: str = ""
    webhook_secret: str = ""
    receipt_secret: str = ""
    callback_secret: str = ""
    internal_api_secret: str = ""
    staging_internal_api_secret: str = ""
    # FocusVPN control plane report for /api/admin/vpn/summary. Empty token disables it.
    focusvpn_api_base: str = "http://127.0.0.1:18080"
    focusvpn_internal_token: str = ""
    signer_base_url: str = ""
    signer_secret_key: str = ""
    signer_api_key: str = "focuspay-main"
    staging_telegram_bot_username: str = ""
    staging_telegram_bot_id: int = 0
    # Comma-separated IDs of dedicated staging chats. Runtime chat bindings must be a subset.
    staging_telegram_chat_ids: str = ""
    # Explicit test-only opt-in: starts HTTP API without workers, event listeners, or external bridges.
    staging_disable_background_tasks: bool = False
    # ID внешнего exchange-account, которому разрешены casino deposits. 0 = fail closed.
    casino_exchanger_id: int = 0
    # Username casino-бота без @ (панель + t.me deep-link входа на сайт). Прод: focusludka_bot.
    casino_bot_username: str = ""
    casino_telegram_bot_token: str = ""

    merchant_base_url: str = ""
    merchant_api_key: str = ""
    merchant_secret_key: str = ""
    merchant_callback_url: str = ""
    merchant_default_sub_token: str = "SBPRUB"
    merchant_id: str = ""
    receipt_public_base_url: str = "https://focuspay.org"

    # Comma-separated in .env: ADMIN_TELEGRAM_IDS=123,456
    admin_telegram_ids: str = ""
    # Telegram user id владельца (единственный, кто видит прибыль). Пусто → первый из admin_telegram_ids
    finance_owner_telegram_id: str = ""


    @cached_property
    def operator_sticker_set_names(self) -> List[str]:
        return [x.strip() for x in self.operator_sticker_sets.split(",") if x.strip()]

    def broadcast_sticker_set_names(self) -> List[str]:
        names = [x.strip() for x in (self.broadcast_sticker_sets or "").split(",") if x.strip()]
        if names:
            return names
        # Empty: do not fall back to a public pack (full-size stickers in broadcasts).
        return []

    def broadcast_ai_provider_names(self) -> List[str]:
        return [
            x.strip().lower()
            for x in (self.broadcast_ai_provider_allowlist or "").split(",")
            if x.strip()
        ]

    def broadcast_ai_model_names(self) -> List[str]:
        return [
            x.strip()
            for x in (self.broadcast_ai_model_allowlist or "").split(",")
            if x.strip()
        ]

    @cached_property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.admin_telegram_ids.split(",") if x.strip()]

    # Pricing config (mirrors tg_bot_btc/services/config_rates.py)
    pricing: dict = {
        "btc":  {"buy_markup": 1.20, "sell_discount": 0.96},
        "usdt": {"buy_markup": 1.20, "sell_discount": 0.96},
        "trx":  {"buy_markup": 1.20, "sell_discount": 0.96},
        "ltc":  {"buy_markup": 1.20, "sell_discount": 0.96},
    }

    amount_limits: dict = {
        "btc":  {"min_crypto": "0.00012",     "max_crypto": "1.00081882", "min_fiat": 1000, "max_fiat": 2000000},
        "usdt": {"min_crypto": "10",          "max_crypto": "50000",      "min_fiat": 1000, "max_fiat": 3000000},
        "trx":  {"min_crypto": "30",          "max_crypto": "200000",     "min_fiat": 1000, "max_fiat": 1000000},
        "ltc":  {"min_crypto": "0.1",         "max_crypto": "500",        "min_fiat": 1000, "max_fiat": 1500000},
    }

    card_fee_auto: float = 0.12    # комиссия провайдера карт (авто-бот)
    card_fee_manual: float = 0.14  # комиссия провайдера карт (ручные)
    buy_spread: float = 0.20       # спред в цене для клиента (buy_markup=1.20)

    merchant_payin_limits: dict = {
        "SBPRUB": {"max_single": 150000, "min_single": 1000},
        "CARDRUB": {"max_single": 150000, "min_single": 1000},
    }
    operator_fallback_min_rub: float = 1000
    user_cashback_percent: float = 5.0
    user_cashback_tier_step_percent: float = 2.0
    user_cashback_tier_every_n: int = 5
    user_cashback_percent_max: float = 15.0
    user_referral_percent: float = 5.0
    user_referral_min_withdraw_card_rub: int = 20000
    casino_min_withdraw_card_rub: int = 20000
    casino_withdraw_fee_card_rub: float = 100.0
    casino_withdraw_fee_usd_btc: float = 2.5
    casino_withdraw_fee_usd_ltc: float = 2.5
    casino_withdraw_fee_usd_trx: float = 2.5
    user_referral_min_withdraw_crypto_usd: float = 10.0
    user_referral_min_withdraw_crypto_usd_btc: float = 5.0
    user_referral_min_withdraw_crypto_usd_ltc: float = 5.0
    user_referral_min_withdraw_crypto_usd_trx: float = 5.0
    user_referral_min_withdraw_crypto_usd_usdt: float = 20.0
    # Legacy env keys still parse; outgoing fees use casino_withdraw_fee_* + usd_usdt.
    crypto_network_fee_rub_btc: float = 50.0
    crypto_network_fee_rub_ltc: float = 20.0
    crypto_network_fee_rub_trx: float = 20.0
    crypto_network_fee_usd_usdt: float = 4.0
    partner_min_withdraw_card_rub: int = 20000
    sell_atm_commission_pct: float = 7.0
    max_payin_chain_parts: int = 3

    geoip_city_db_path: str = ""
    security_log_file: str = ""
    redis_url: str = ""
    # HttpOnly cookies для /x8 и /ops (дополнительно к Bearer в localStorage)
    panel_http_only_cookies: bool = True
    security_ip_ban_score: int = 70
    security_ip_ban_sec: int = 3600
    # Comma-separated: never auto-ban / rate-limit (owner office, VPN exit)
    security_trusted_ips: str = ""
    # Comma-separated: selfcheck / server public IP — probe alerts suppressed (still logged)
    security_internal_ips: str = ""
    # Comma-separated CIDRs/IPs of reverse proxies allowed to set X-Forwarded-For / CF-Connecting-IP
    security_trusted_proxies: str = "127.0.0.1,::1"
    security_rate_limit_per_min: int = 240
    security_alert_cooldown_sec: int = 900
    security_alerts_enabled: bool = True
    # Shared secret for deploy status webhook (header X-FocusPay-Deploy-Signature, never URL)
    deploy_webhook_secret: str = ""
    battle_enabled: bool = False
    # Prod: false — не отдавать /docs и /openapi.json (разведка API)
    expose_openapi_docs: bool = False
    # Localhost CORS только для dev (EXPOSE_LOCAL_CORS=1). На prod — public_site_url + CORS_ORIGINS.
    expose_local_cors: bool = False
    cors_origins: str = ""  # comma-separated extra origins

    security_auth_fail_threshold: int = 5
    security_auth_fail_window_sec: int = 300
    # Ban scanner/rate_flood/operator_probe after N hits in window
    security_probe_ban_threshold: int = 5
    security_probe_ban_window_sec: int = 600
    # App ban → fail2ban-client (network level)
    security_fail2ban_bridge: bool = True
    security_fail2ban_bridge_script: str = "/usr/local/sbin/focuspay-ban-bridge.sh"
    # Security agent auto-ban thresholds (also used by agent service)
    security_agent_auto_ban_threshold: int = 8
    security_agent_auto_ban_window_sec: int = 900

    # Внештатные обмены (изолированный учёт долга в USDT для людей вне бота)
    ext_markup_pct: float = 20.0            # наценка на клиента (%)
    ext_markup_mode: str = "on_deal"        # on_deal | on_turnover
    ext_card_fee_pct: float = 0.12          # комиссия пейфаст (доля, 0.12 = 12%)
    ext_receive_fee_usd: float = 0.0        # потеря при получении монет (0 — учитывается только при выводе)
    ext_withdraw_fee_usd: float = 3.0       # комиссия при выводе ($)

    # Doliv lab bridge (trader card payouts) — empty = disabled
    doliv_bridge_url: str = ""
    doliv_bridge_key: str = ""

    # Алерты безопасности — отдельно от TELEGRAM_ADMIN_GROUP_ID (ордера, финансы).
    # Группа: SECURITY_TELEGRAM_CHAT_ID=-100… (бот должен быть в группе).
    # Личка @focus_operator: SECURITY_TELEGRAM_USER_ID=1097952683 (если chat_id не задан).
    security_telegram_chat_id: int = 0
    security_telegram_user_id: int = 0

    # Ops AI (чат оператора + задачи → Approve)
    ops_ai_provider: str = "openai"  # openai | openrouter | anthropic | offline
    ops_ai_openai_api_key: str = ""
    ops_ai_openai_base_url: str = "https://api.openai.com/v1"
    ops_ai_openai_model: str = "gpt-4.1-mini"
    # OpenRouter (OpenAI-compatible): https://openrouter.ai/api/v1
    ops_ai_openrouter_api_key: str = ""
    ops_ai_openrouter_model: str = "openai/gpt-4o-mini"
    ops_ai_openrouter_site_url: str = "https://focuspay.org"
    ops_ai_openrouter_app_name: str = "FocusPay Ops AI"
    ops_ai_anthropic_api_key: str = ""
    ops_ai_anthropic_model: str = "claude-sonnet-4-20250514"
    ops_ai_knowledge_roots: str = ""  # comma-separated dirs
    ops_ai_rate_per_min: int = 20
    ops_ai_dev_telegram_chat_id: int = 0  # 0 = admin/ops group

    ops_ai_vision_model: str = "gpt-4.1-mini"
    ops_ai_upload_dir: str = "/var/lib/focuspay/ops_ai"
    ops_ai_multi_agent: str = "0"
    ops_ai_agent_model: str = ""
    # Privacy / audit (no secrets)
    ops_ai_consent_version: str = "ops-ai-privacy-v1"
    ops_ai_audit_ttl_days: int = 30
    ops_ai_allow_images: bool = False
    ops_ai_allow_ui_client_pii: bool = False
    ops_ai_allow_order_amounts: bool = False
    news_broadcast_rate_per_min: int = 30
    news_broadcast_frequency_hours: int = 24
    news_broadcast_max_recipients: int = 50000

    # Sticker AI (isolated from Ops AI). Default OFF — no generate/publish side effects.
    sticker_ai_enabled: bool = False
    # Separate gate for create/generate/approve/publish HTTP. Keep false until lab enable.
    sticker_ai_mutations_enabled: bool = False
    sticker_ai_provider: str = "null"  # null | offline_mock | lelouch | openai | http_worker
    sticker_ai_image_model: str = "gpt-image-2"  # Lelouch image model; no secrets
    sticker_ai_worker_base_url: str = ""
    sticker_ai_worker_token: str = ""  # secret manager / env only — never log / never commit
    sticker_ai_tg_admin_ids: str = ""
    sticker_ai_tg_chat_ids: str = ""
    sticker_ai_rate_per_min: int = 20
    sticker_ai_tenant_id: str = "focuspay"

    @field_validator(
        "security_telegram_chat_id",
        "security_telegram_user_id",
        "telegram_ops_group_id",
        "telegram_external_deals_group_id",
        "telegram_reports_group_id",
        "telegram_news_chat_id",
        "ops_ai_dev_telegram_chat_id",
        "casino_exchanger_id",
        "staging_telegram_bot_id",
        mode="before",
    )
    @classmethod
    def _empty_int_zero(cls, v):
        if v is None or v == "":
            return 0
        return v

    def ops_telegram_group_id(self) -> int:
        return int(self.telegram_ops_group_id or self.telegram_admin_group_id or 0)

    def external_deals_telegram_group_id(self) -> int:
        ext = int(self.telegram_external_deals_group_id or 0)
        if ext:
            return ext
        return self.ops_telegram_group_id()

    def reports_telegram_group_id(self) -> int:
        return int(
            self.telegram_reports_group_id
            or self.telegram_admin_group_id
            or 0
        )

    sell_wallets_json: str = ""

    @cached_property
    def sell_wallets(self) -> dict:
        raw = (self.sell_wallets_json or os.environ.get("SELL_WALLETS_JSON") or "").strip()
        if raw:
            return json.loads(raw)
        return {
            "usdt": {"trc20": "", "erc20": "", "bep20": "", "arbitrum": "", "solana": ""},
            "btc": {"mainnet": ""},
            "trx": {"mainnet": ""},
            "ltc": {"mainnet": ""},
        }

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


_STAGING_PRODUCTION_HOSTS = {"focuspay.org"}
_STAGING_PRODUCTION_IPS = {"153.80.249.77"}
_STAGING_PLACEHOLDER_MARKERS = ("change_me", "placeholder", "replace_", "example")


def _is_staging_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in _STAGING_PLACEHOLDER_MARKERS)


def _validate_staging_target(name: str, value: str, schemes: set[str]) -> None:
    if _is_staging_placeholder(value):
        raise RuntimeError(f"FATAL: staging {name} must be explicitly configured")

    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in schemes or not host:
        raise RuntimeError(f"FATAL: staging {name} must be an absolute allowed URL")
    if host in _STAGING_PRODUCTION_IPS or host == "focuspay.org" or host.endswith(".focuspay.org"):
        raise RuntimeError(f"FATAL: staging {name} must not target a production host")


def _parse_staging_chat_ids(value: str) -> set[int]:
    try:
        chat_ids = {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise RuntimeError("FATAL: staging Telegram chat allowlist must contain integer IDs") from exc
    if not chat_ids or any(chat_id == 0 for chat_id in chat_ids):
        raise RuntimeError("FATAL: staging Telegram chat allowlist must be configured")
    return chat_ids


def validate_staging_config(candidate: Settings) -> None:
    """Reject incomplete or production-directed configuration before staging startup."""
    if (candidate.environment or "").strip().lower() != "staging":
        return

    required_values = {
        "database_dsn": candidate.database_dsn,
        "redis_url": candidate.redis_url,
        "secret_key": candidate.secret_key,
        "internal_api_secret": candidate.internal_api_secret,
        "staging_internal_api_secret": candidate.staging_internal_api_secret,
        "telegram_bot_token": candidate.telegram_bot_token,
    }
    for name, value in required_values.items():
        if _is_staging_placeholder(str(value or "")):
            raise RuntimeError(f"FATAL: staging {name} must be explicitly configured")

    if candidate.internal_api_secret != candidate.staging_internal_api_secret:
        raise RuntimeError("FATAL: staging internal API secret confirmation failed")
    if len((candidate.secret_key or "").strip()) < 32:
        raise RuntimeError("FATAL: staging SECRET_KEY must be at least 32 characters")
    if int(candidate.casino_exchanger_id or 0) <= 0:
        raise RuntimeError("FATAL: staging CASINO_EXCHANGER_ID must be positive")

    username = (candidate.telegram_bot_username or "").strip().lstrip("@")
    allowed_username = (candidate.staging_telegram_bot_username or "").strip().lstrip("@")
    allowed_id = int(candidate.staging_telegram_bot_id or 0)
    if not allowed_username and allowed_id <= 0:
        raise RuntimeError("FATAL: staging Telegram bot allowlist must be configured")
    if allowed_username and username.lower() != allowed_username.lower():
        raise RuntimeError("FATAL: staging Telegram bot username is not allowlisted")
    allowed_chat_ids = _parse_staging_chat_ids(candidate.staging_telegram_chat_ids)
    configured_chat_ids = {
        chat_id
        for chat_id in (
            candidate.telegram_admin_group_id,
            candidate.telegram_ops_group_id,
            candidate.telegram_external_deals_group_id,
            candidate.telegram_reports_group_id,
            candidate.telegram_news_chat_id,
        )
        if chat_id
    }
    if not configured_chat_ids.issubset(allowed_chat_ids):
        raise RuntimeError("FATAL: staging Telegram chat is not allowlisted")

    _validate_staging_target("DATABASE_DSN", candidate.database_dsn, {"postgresql", "postgres"})
    _validate_staging_target("REDIS_URL", candidate.redis_url, {"redis", "rediss"})
    _validate_staging_target("PUBLIC_SITE_URL", candidate.public_site_url, {"http", "https"})
    _validate_staging_target("MERCHANT_BASE_URL", candidate.merchant_base_url, {"http", "https"})
    _validate_staging_target("MERCHANT_CALLBACK_URL", candidate.merchant_callback_url, {"http", "https"})
    _validate_staging_target("RECEIPT_PUBLIC_BASE_URL", candidate.receipt_public_base_url, {"http", "https"})


settings = Settings()
validate_staging_config(settings)


def validate_production_config() -> None:
    key = (settings.secret_key or "").strip()
    if len(key) < 32:
        raise RuntimeError("FATAL: set SECRET_KEY in .env (min 32 chars)")
