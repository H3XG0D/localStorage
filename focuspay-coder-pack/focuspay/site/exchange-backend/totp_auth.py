"""TOTP 2FA для админ-панели."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

TOTP_INTERVAL = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1


def generate_totp_secret() -> str:
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> int:
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode((secret_b32 + pad).upper(), casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return code % (10**TOTP_DIGITS)


def verify_totp_code(secret: str | None, code: str | None) -> bool:
    if not secret or not code:
        return False
    code = str(code).strip().replace(" ", "")
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    now = int(time.time())
    step = now // TOTP_INTERVAL
    for offset in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        if str(_hotp(secret, step + offset)).zfill(TOTP_DIGITS) == code:
            return True
    return False


def totp_provisioning_uri(*, secret: str, username: str, issuer: str = "FocusPay") -> str:
    label = f"{issuer}:{username}"
    from urllib.parse import quote

    return (
        f"otpauth://totp/{quote(label)}?secret={secret}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_INTERVAL}"
    )
