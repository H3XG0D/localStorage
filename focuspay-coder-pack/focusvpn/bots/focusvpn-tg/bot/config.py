"""Config for FocusVPN Telegram bot."""

from __future__ import annotations

import os


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
FOCUSPAY_API_BASE = env("FOCUSPAY_API_BASE", "http://127.0.0.1:8081").rstrip("/")
FOCUSPAY_INTERNAL_TOKEN = env("FOCUSPAY_INTERNAL_TOKEN") or env("VPN_INTERNAL_TOKEN")
FOCUSVPN_API_BASE = env("FOCUSVPN_API_BASE", "http://127.0.0.1:8080").rstrip("/")
FOCUSVPN_INTERNAL_TOKEN = env("FOCUSVPN_INTERNAL_TOKEN")
VPN_CLIENT_DOWNLOAD_URL = env("VPN_CLIENT_DOWNLOAD_URL", "https://focuspay.org/vpn.apk")
# The bot sends this file into the chat. Telegram's in-app browser does not save APKs.
VPN_APK_PATH = env("VPN_APK_PATH", "/var/www/focuspay.org/vpn.apk")
VPN_APK_FILE_ID_PATH = env("VPN_APK_FILE_ID_PATH", "/opt/focusvpn/bot/apk.file_id.json")
# FocusPay exchange bot: exchanges there unlock VPN plans.
FOCUSPAY_BOT_URL = env("FOCUSPAY_BOT_URL", "https://t.me/focuspay1_bot")
REVIEWS_CHANNEL_URL = env("REVIEWS_CHANNEL_URL", "https://t.me/focuspayr")
REMINDER_INTERVAL_SEC = int(env("VPN_REMINDER_INTERVAL_SEC", "600") or "600")
# auto: tg-emoji and button icons, with a Unicode retry if Telegram rejects them.
# off: ordinary emoji from the start.
PREMIUM_EMOJI = env("PREMIUM_EMOJI", "auto").lower() != "off"
