from __future__ import annotations

import pytest

from config import Settings, validate_staging_config


VALID_STAGING = {
    "environment": "staging",
    "database_dsn": "postgresql://staging:password@postgres:5432/focuspay_staging",
    "redis_url": "redis://redis:6379/0",
    "secret_key": "s" * 32,
    "internal_api_secret": "staging-internal-secret",
    "staging_internal_api_secret": "staging-internal-secret",
    "casino_exchanger_id": 1001,
    "telegram_bot_token": "test-token",
    "telegram_bot_username": "focuspay_staging_bot",
    "staging_telegram_bot_username": "focuspay_staging_bot",
    "staging_telegram_bot_id": 100000001,
    "staging_telegram_chat_ids": "-1000000000001,-1000000000002",
    "public_site_url": "http://backend:8000",
    "merchant_base_url": "http://fake-payfast:8081",
    "merchant_callback_url": "http://backend:8000/api/webhook/payfast",
    "receipt_public_base_url": "http://backend:8000",
}


def staging_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **(VALID_STAGING | overrides))


def test_accepts_explicitly_isolated_staging_config() -> None:
    validate_staging_config(staging_settings())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_site_url", "https://focuspay.org"),
        ("merchant_base_url", "https://merchant.focuspay.org"),
        ("merchant_callback_url", "https://153.80.249.77/callback"),
        ("receipt_public_base_url", "https://focuspay.org/receipt"),
        ("database_dsn", "postgresql://staging:password@153.80.249.77:5432/focuspay"),
        ("redis_url", "redis://153.80.249.77:6379/0"),
    ],
)
def test_rejects_production_staging_targets(field: str, value: str) -> None:
    with pytest.raises(RuntimeError, match="production host"):
        validate_staging_config(staging_settings(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_dsn", ""),
        ("redis_url", ""),
        ("secret_key", "placeholder"),
        ("internal_api_secret", ""),
        ("staging_internal_api_secret", ""),
        ("telegram_bot_token", ""),
        ("merchant_base_url", "https://placeholder.invalid"),
        ("internal_api_secret", "REPLACE_WITH_STAGING_INTERNAL_API_SECRET"),
    ],
)
def test_rejects_missing_or_placeholder_staging_values(field: str, value: str) -> None:
    with pytest.raises(RuntimeError):
        validate_staging_config(staging_settings(**{field: value}))


def test_rejects_unconfirmed_internal_secret() -> None:
    with pytest.raises(RuntimeError, match="secret confirmation"):
        validate_staging_config(
            staging_settings(staging_internal_api_secret="different-staging-secret")
        )


def test_rejects_non_positive_casino_exchanger_id() -> None:
    with pytest.raises(RuntimeError, match="CASINO_EXCHANGER_ID"):
        validate_staging_config(staging_settings(casino_exchanger_id=0))


def test_rejects_missing_telegram_allowlist() -> None:
    with pytest.raises(RuntimeError, match="Telegram bot allowlist"):
        validate_staging_config(
            staging_settings(staging_telegram_bot_username="", staging_telegram_bot_id=0)
        )


def test_rejects_unallowlisted_telegram_username() -> None:
    with pytest.raises(RuntimeError, match="username is not allowlisted"):
        validate_staging_config(
            staging_settings(staging_telegram_bot_username="another_staging_bot")
        )


@pytest.mark.parametrize("chat_ids", ["", "0", "not-an-id", "-1000000000001,wrong"])
def test_rejects_missing_or_invalid_staging_chat_allowlist(chat_ids: str) -> None:
    with pytest.raises(RuntimeError, match="Telegram chat allowlist"):
        validate_staging_config(staging_settings(staging_telegram_chat_ids=chat_ids))


def test_rejects_configured_chat_outside_staging_allowlist() -> None:
    with pytest.raises(RuntimeError, match="Telegram chat is not allowlisted"):
        validate_staging_config(
            staging_settings(
                telegram_ops_group_id=-1000000000999,
                staging_telegram_chat_ids="-1000000000001",
            )
        )


def test_non_staging_configuration_is_not_constrained_by_staging_guard() -> None:
    validate_staging_config(
        Settings(
            _env_file=None,
            environment="production",
            public_site_url="https://focuspay.org",
        )
    )
