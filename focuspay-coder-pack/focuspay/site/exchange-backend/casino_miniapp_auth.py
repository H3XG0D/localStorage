"""Verify casino Mini App credentials before issuing an ordinary user session."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException


def verify_casino_init_data(raw: str, bot_token: str, *, now: float | None = None) -> dict:
    if not bot_token:
        raise HTTPException(503, 'Вход через игрового бота временно недоступен')
    pairs = parse_qsl(raw, keep_blank_values=True)
    data = dict(pairs)
    if len(data) != len(pairs) or not data.get('hash'):
        raise HTTPException(401, 'Некорректные данные Telegram')
    check = '\n'.join(f'{key}={value}' for key, value in sorted(pairs) if key != 'hash')
    secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, data['hash']):
        raise HTTPException(401, 'Некорректная подпись Telegram')
    try:
        age = (time.time() if now is None else now) - int(data['auth_date'])
        user = json.loads(data['user'])
        uid = user['id']
        if age < -30 or age > 3600 or type(uid) is not int or uid <= 0:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, 'Откройте Mini App заново: данные входа устарели') from None
    return user
