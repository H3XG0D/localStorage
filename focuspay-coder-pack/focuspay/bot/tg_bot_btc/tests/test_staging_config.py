"""Fail-closed configuration checks for the isolated staging bot."""
from __future__ import annotations

import pytest

from services import config_rates


SAFE_STAGING_ENV = {
    "STAGING_TELEGRAM_BOT_USERNAME": "focuspay_staging_bot",
    "STAGING_TELEGRAM_BOT_ID": "1001",
    "TELEGRAM_BOT_USERNAME": "@focuspay_staging_bot",
    "TELEGRAM_BOT_ID": "1001",
    "TELEGRAM_ADMIN_GROUP_ID": "-10001",
    "TELEGRAM_OPS_GROUP_ID": "-10002",
    "TELEGRAM_REPORTS_GROUP_ID": "-10003",
    "TELEGRAM_EXTERNAL_DEALS_GROUP_ID": "-10004",
    "TELEGRAM_CLIENT_REVIEW_GROUP_ID": "-10005",
    "TELEGRAM_APPEALS_GROUP_ID": "-10006",
    "TELEGRAM_COMMUNITY_CHAT_ID": "-10007",
    "TELEGRAM_NEWS_CHAT_ID": "-10008",
    "REVIEWS_PUBLISH_CHAT_ID": "-10009",
    "PUBLIC_SITE_URL": "https://focuspay.staging.test",
    "EXCHANGE_API_URL": "http://backend.staging.test:8000",
    "MERCHANT_BASE_URL": "https://merchant.staging.test/api",
    "MERCHANT_CALLBACK_URL": "https://focuspay.staging.test/callback",
    "TELEGRAM_WEBHOOK_URL": "https://bot.staging.test/telegram",
    "DATABASE_DSN": "postgresql://bot@db.staging.test/bot",
}


def test_staging_config_accepts_isolated_identity_chats_and_endpoints():
    assert config_rates.validate_staging_config(SAFE_STAGING_ENV) == []


def test_staging_config_requires_distinct_bot_identity_and_all_chats():
    env = SAFE_STAGING_ENV.copy()
    env.pop("TELEGRAM_NEWS_CHAT_ID")
    env["TELEGRAM_BOT_ID"] = "2002"

    errors = config_rates.validate_staging_config(env)

    assert "missing TELEGRAM_NEWS_CHAT_ID" in errors
    assert "TELEGRAM_BOT_ID does not match STAGING_TELEGRAM_BOT_ID" in errors


def test_staging_config_accepts_allowlisted_bot_username_without_marker():
    env = SAFE_STAGING_ENV | {
        "STAGING_TELEGRAM_BOT_USERNAME": "focuspay_bot",
        "TELEGRAM_BOT_USERNAME": "focuspay_bot",
    }

    assert config_rates.validate_staging_config(env) == []


def test_staging_config_accepts_compose_internal_endpoints():
    env = SAFE_STAGING_ENV | {
        "PUBLIC_SITE_URL": "http://gateway:8080",
        "EXCHANGE_API_URL": "http://backend:8000",
        "MERCHANT_BASE_URL": "http://fake-payfast:8081",
        "MERCHANT_CALLBACK_URL": "http://backend:8000/api/webhook/payfast",
        "DATABASE_DSN": "postgresql://bot@postgres:5432/bot",
    }

    assert config_rates.validate_staging_config(env) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PUBLIC_SITE_URL", "https://focuspay.org"),
        ("EXCHANGE_API_URL", "https://153.80.249.77"),
        ("MERCHANT_BASE_URL", "https://payfast.website/api_merchant"),
        ("MERCHANT_CALLBACK_URL", "https://focuspay.org/callback"),
        ("TELEGRAM_WEBHOOK_URL", "https://focuspay.org/bot/telegram"),
        ("DATABASE_DSN", "postgresql://bot@153.80.249.77/bot"),
    ],
)
def test_staging_config_rejects_production_endpoints(key, value):
    env = SAFE_STAGING_ENV | {key: value}

    errors = config_rates.validate_staging_config(env)

    assert f"{key} must use a local, private, or explicitly staging endpoint" in errors


def test_staging_background_and_polling_flags_are_fail_closed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("STAGING_ENABLE_SAFE_BACKGROUND_TASKS", raising=False)
    assert not config_rates.background_tasks_enabled()
    assert config_rates.polling_drops_pending_updates()

    monkeypatch.setenv("STAGING_ENABLE_SAFE_BACKGROUND_TASKS", "true")
    assert config_rates.background_tasks_enabled()


def test_production_background_and_polling_flags_preserve_existing_behavior(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("STAGING_ENABLE_SAFE_BACKGROUND_TASKS", raising=False)
    assert config_rates.background_tasks_enabled()
    assert not config_rates.polling_drops_pending_updates()


def test_staging_polling_lock_prevents_parallel_local_processes(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("STAGING_POLLING_LOCK_PATH", str(tmp_path / "polling.lock"))
    lock = config_rates.acquire_staging_polling_lock()
    try:
        with pytest.raises(SystemExit):
            config_rates.acquire_staging_polling_lock()
    finally:
        lock.close()
