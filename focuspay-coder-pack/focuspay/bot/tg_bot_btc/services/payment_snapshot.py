"""Единственный парсер orders.payment_snapshot.

asyncpg отдаёт jsonb строкой, пока на пул не навешан кодек, поэтому читать
снапшот напрямую нельзя: `dict("{...}")` падает с «dictionary update sequence
element #0 has length 1; 2 is required». Раньше эта проверка была скопирована
по 11 файлам, и там, где её забыли, уведомление о закрытии реквизитов PayFast
молча падало 546 раз за неделю. Весь код читает снапшот только через этот
модуль; зависимостей у него нет, чтобы его можно было импортировать откуда
угодно без циклов.
"""
from __future__ import annotations

import json


def parse_payment_snapshot(snap) -> dict:
    """Снапшот как dict. Мусор, строка-не-JSON и None дают пустой dict."""
    if isinstance(snap, dict):
        return dict(snap)
    if isinstance(snap, str) and snap.strip():
        try:
            parsed = json.loads(snap)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def reki_payfast_id(order) -> str:
    """UUID реки. Не merchant_uuid: в наш PayFast его передавать нельзя."""
    raw = order_payment_snapshot(order).get("reki_payfast_id")
    if isinstance(raw, str):
        return raw.strip()
    return ""


def order_payment_snapshot(order) -> dict:
    """Снапшот заявки/сделки: принимает dict и asyncpg.Record."""
    if order is None:
        return {}
    getter = getattr(order, "get", None)
    if callable(getter):
        return parse_payment_snapshot(getter("payment_snapshot"))
    try:
        return parse_payment_snapshot(order["payment_snapshot"])
    except (KeyError, IndexError, TypeError):
        return {}
