from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
VALID_STAGING = {
    "ENVIRONMENT": "staging",
    "BOT_TOKEN": "test-token",
    "BOT_USERNAME": "focuscasino_staging_bot",
    "CASINO_STAGING_TELEGRAM_BOT_USERNAME": "focuscasino_staging_bot",
    "CASINO_STAGING_TELEGRAM_BOT_ID": "100000002",
    "FOCUSPAY_API_URL": "http://backend:8000",
    "FOCUSPAY_INTERNAL_TOKEN": "staging-internal-secret",
    "STAGING_INTERNAL_API_SECRET": "staging-internal-secret",
    "CASINO_EXCHANGER_ID": "1001",
    "WEBHOOK_URL": "http://casino-bot:8001/webhook",
    "GAME_CHAT_ID": "-1000000000001",
    "ALLOWED_CHAT_ID": "-1000000000001",
    "ADMIN_IDS": "100000003",
}


def load_config_without_dotenv() -> object:
    module_name = "staging_config_test_module"
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        with patch("dotenv.load_dotenv", return_value=False):
            spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


def validate(**overrides: str) -> None:
    with patch.dict(os.environ, VALID_STAGING | overrides, clear=True):
        config = load_config_without_dotenv()
        config.validate_staging_config(dict(os.environ))


def test_accepts_explicitly_isolated_staging_config() -> None:
    validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("FOCUSPAY_API_URL", "https://focuspay.org"),
        ("FOCUSPAY_API_URL", "https://api.focuspay.org"),
        ("FOCUSPAY_API_URL", "https://153.80.249.77"),
        ("WEBHOOK_URL", "https://casino.focuspay.org/webhook"),
    ],
)
def test_rejects_production_staging_targets(field: str, value: str) -> None:
    with pytest.raises(RuntimeError, match="production host"):
        validate(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("BOT_TOKEN", ""),
        ("FOCUSPAY_API_URL", ""),
        ("FOCUSPAY_INTERNAL_TOKEN", ""),
        ("STAGING_INTERNAL_API_SECRET", ""),
        ("WEBHOOK_URL", ""),
        ("BOT_TOKEN", "placeholder"),
        ("FOCUSPAY_INTERNAL_TOKEN", "REPLACE_WITH_STAGING_INTERNAL_API_SECRET"),
    ],
)
def test_rejects_missing_or_placeholder_staging_values(field: str, value: str) -> None:
    with pytest.raises(RuntimeError):
        validate(**{field: value})


def test_rejects_unconfirmed_internal_secret() -> None:
    with pytest.raises(RuntimeError, match="secret confirmation"):
        validate(STAGING_INTERNAL_API_SECRET="different-staging-secret")


def test_rejects_non_positive_casino_exchanger_id() -> None:
    with pytest.raises(RuntimeError, match="CASINO_EXCHANGER_ID"):
        validate(CASINO_EXCHANGER_ID="0")


def test_rejects_missing_telegram_allowlist() -> None:
    with pytest.raises(RuntimeError, match="Telegram bot allowlist"):
        validate(CASINO_STAGING_TELEGRAM_BOT_USERNAME="", CASINO_STAGING_TELEGRAM_BOT_ID="0")


def test_rejects_unallowlisted_telegram_username() -> None:
    with pytest.raises(RuntimeError, match="username is not allowlisted"):
        validate(CASINO_STAGING_TELEGRAM_BOT_USERNAME="another_staging_bot")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GAME_CHAT_ID", "0"),
        ("GAME_CHAT_ID", "100000003"),
        ("ALLOWED_CHAT_ID", "-1000000000999"),
        ("ADMIN_IDS", ""),
    ],
)
def test_rejects_missing_or_invalid_casino_chat_allowlist(field: str, value: str) -> None:
    with pytest.raises(RuntimeError, match="casino chat/admin allowlist"):
        validate(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GAME_CHAT_ID", "not-a-chat"),
        ("ALLOWED_CHAT_ID", "not-a-chat"),
        ("ADMIN_IDS", "not-an-admin"),
    ],
)
def test_rejects_non_numeric_casino_telegram_ids(field: str, value: str) -> None:
    with pytest.raises(RuntimeError, match="Telegram IDs must be numeric"):
        validate(**{field: value})


def test_staging_ui_v2_is_enabled_only_for_explicit_staging_flag() -> None:
    with patch.dict(os.environ, VALID_STAGING | {"CASINO_STAGING_UI_V2": "1"}, clear=True):
        assert load_config_without_dotenv().CASINO_STAGING_UI_V2 is True
    with patch.dict(
        os.environ,
        {"ENVIRONMENT": "production", "CASINO_STAGING_UI_V2": "1"},
        clear=True,
    ):
        assert load_config_without_dotenv().CASINO_STAGING_UI_V2 is False


def test_non_staging_configuration_is_not_constrained_by_staging_guard() -> None:
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
        config = load_config_without_dotenv()
        config.validate_staging_config(dict(os.environ))


def test_derives_miniapp_url_from_fairness() -> None:
    with patch.dict(
        os.environ,
        VALID_STAGING | {"CASINO_FAIRNESS_URL": "http://127.0.0.1:18081/casino/fairness"},
        clear=True,
    ):
        config = load_config_without_dotenv()
        assert config.CASINO_MINIAPP_URL == "http://127.0.0.1:18081/casino/tg"


def test_explicit_miniapp_url_wins() -> None:
    with patch.dict(
        os.environ,
        VALID_STAGING
        | {
            "CASINO_FAIRNESS_URL": "http://127.0.0.1:18081/casino/fairness",
            "CASINO_MINIAPP_URL": "https://example.test/casino/tg",
        },
        clear=True,
    ):
        config = load_config_without_dotenv()
        assert config.CASINO_MINIAPP_URL == "https://example.test/casino/tg"


def test_empty_fairness_does_not_invent_miniapp_url() -> None:
    with patch.dict(os.environ, VALID_STAGING, clear=True):
        config = load_config_without_dotenv()
        assert config.CASINO_MINIAPP_URL == ""


def test_deposits_default_on_for_staging() -> None:
    with patch.dict(os.environ, VALID_STAGING, clear=True):
        assert load_config_without_dotenv().DEPOSITS_ENABLED is True


def test_deposits_explicit_off_on_staging() -> None:
    with patch.dict(os.environ, VALID_STAGING | {"DEPOSITS_ENABLED": "0"}, clear=True):
        assert load_config_without_dotenv().DEPOSITS_ENABLED is False


def test_deposits_default_off_outside_staging() -> None:
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
        assert load_config_without_dotenv().DEPOSITS_ENABLED is False


def test_deposits_explicit_on_outside_staging() -> None:
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "DEPOSITS_ENABLED": "1"}, clear=True):
        assert load_config_without_dotenv().DEPOSITS_ENABLED is True
