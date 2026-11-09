"""Клиент finance666: выплаты по QR СБП с мерчантского USDT-баланса.

Рельс выплатной: `check` проверяет отсканированный код и возвращает сумму с комиссией,
`pay` проводит выплату. Проверка живёт 30 секунд, средства морозятся на `pay`.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

logger = logging.getLogger("finance666")

REQUEST_TIMEOUT_SEC = 12

# Группы статусов общие для всех способов выплаты. Список кодов открыт: решение
# принимаем по группе, завершённость — по is_final.
GROUP_PROCESSING = "PROCESSING"
GROUP_SUCCEEDED = "SUCCEEDED"
GROUP_DECLINED = "DECLINED"
GROUP_FAILED = "FAILED"
GROUP_REFUNDED = "REFUNDED"

FINAL_GROUPS = frozenset({GROUP_SUCCEEDED, GROUP_DECLINED, GROUP_FAILED, GROUP_REFUNDED})

# Единственный код, при котором выплату можно проводить.
CODE_CHECKED = "CHECKED"
CODE_INSUFFICIENT_FUNDS = "MERCHANT_INSUFFICIENT_FUNDS"

QR_HOST = "qr.nspk.ru"


class Finance666Error(RuntimeError):
    """Сбой связи или нечитаемый ответ. Исход выплаты неизвестен."""


@dataclass
class PaymentStatus:
    group: str
    code: str
    is_final: bool

    @property
    def succeeded(self) -> bool:
        return self.group == GROUP_SUCCEEDED

    @property
    def payable(self) -> bool:
        return self.code == CODE_CHECKED

    @property
    def refunded(self) -> bool:
        return self.group == GROUP_REFUNDED

    @property
    def lost(self) -> bool:
        """Отказ или сбой: заморозка снята, деньги клиенту вернуть."""
        return self.group in (GROUP_DECLINED, GROUP_FAILED)

    @property
    def unknown_outcome(self) -> bool:
        """Незнакомая группа при is_final — исход неопределён, нужен оператор."""
        return self.is_final and self.group not in FINAL_GROUPS


@dataclass
class Payment:
    """Ответ check / pay / status. Незаполненные поля платформа не присылает."""

    transaction_id: str
    status: PaymentStatus
    success: bool = True
    merchant_transaction_id: str | None = None
    amount_in_currency: Decimal | None = None
    currency: str | None = None
    amount_usdt: Decimal | None = None
    fee_usdt: Decimal | None = None
    payee_name: str | None = None
    method: str | None = None
    qr_code: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    is_balance_sufficient: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_usdt(self) -> Decimal:
        return (self.amount_usdt or Decimal(0)) + (self.fee_usdt or Decimal(0))


def is_nspk_qr(qr_code: str) -> bool:
    """Платформа платит только по СБП-кодам, остальное до API не доводим."""
    from urllib.parse import urlparse

    raw = (qr_code or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host == QR_HOST or host.endswith(f".{QR_HOST}")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        logger.warning("finance666: bad decimal %r", value)
        return None


def parse_status(raw: Any) -> PaymentStatus:
    data = raw if isinstance(raw, dict) else {}
    group = str(data.get("group") or "").strip().upper()
    code = str(data.get("code") or "").strip().upper()
    is_final = bool(data.get("is_final"))
    if group and group not in FINAL_GROUPS and group != GROUP_PROCESSING:
        logger.warning("finance666: unknown status group=%s code=%s", group, code)
    return PaymentStatus(group=group, code=code, is_final=is_final)


def parse_payment(data: dict[str, Any]) -> Payment:
    return Payment(
        transaction_id=str(data.get("transaction_id") or ""),
        status=parse_status(data.get("status")),
        success=bool(data.get("success", True)),
        merchant_transaction_id=(
            str(data["merchant_transaction_id"])
            if data.get("merchant_transaction_id") is not None
            else None
        ),
        amount_in_currency=_decimal(data.get("amount_in_currency")),
        currency=data.get("currency"),
        amount_usdt=_decimal(data.get("amount_usdt")),
        fee_usdt=_decimal(data.get("fee_usdt")),
        payee_name=data.get("payee_name"),
        method=data.get("method"),
        qr_code=data.get("qr_code"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        expires_at=data.get("expires_at"),
        is_balance_sufficient=data.get("is_balance_sufficient"),
        raw=data,
    )


def _base_url() -> str:
    from services import config_rates

    return str(getattr(config_rates, "FINANCE666_BASE_URL", "")).rstrip("/")


def _api_key() -> str:
    from services import config_rates

    return str(getattr(config_rates, "FINANCE666_API_KEY", "")).strip()


def configured() -> bool:
    return bool(_base_url() and _api_key())


async def _request(method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
    if not configured():
        raise Finance666Error("FINANCE666_API_KEY не задан")
    url = f"{_base_url()}{path}"
    headers = {
        "X-Api-Key": _api_key(),
        # Платформа отдаёт brotli, если его предложить, а aiohttp без пакета brotli
        # такой ответ декодировать не умеет — просим то, что он точно разберёт.
        "Accept-Encoding": "gzip, deflate",
    }
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, url, json=payload, headers=headers
            ) as response:
                text = await response.text()
                try:
                    data = await response.json(content_type=None)
                except Exception:
                    data = None
                if not isinstance(data, dict):
                    raise Finance666Error(
                        f"{method} {path} -> {response.status}: {text[:200]}"
                    )
                if response.status >= 400 and not data.get("error"):
                    logger.warning(
                        "finance666 %s %s -> %s: %s", method, path, response.status, text[:200]
                    )
                return data
    except aiohttp.ClientError as exc:
        raise Finance666Error(f"{method} {path} failed: {exc}") from exc
    except asyncio.TimeoutError as exc:
        # На Python 3.10 это не встроенный TimeoutError, ловим явно.
        raise Finance666Error(f"{method} {path} timeout") from exc


async def merchant_balance() -> dict[str, Any]:
    """GET /v1/merchant/balance — заодно health-чек ключа и allowlist IP."""
    data = await _request("GET", "/v1/merchant/balance")
    return {
        "success": bool(data.get("success")),
        "available_balance": _decimal(data.get("available_balance")),
        "hold_balance": _decimal(data.get("hold_balance")),
        "currency": data.get("currency"),
    }


async def qr_check(qr_code: str, merchant_transaction_id: str) -> Payment:
    """Проверка кода. Платить можно только при статусе CHECKED и до expires_at."""
    data = await _request(
        "POST",
        "/v1/payments/qr/check",
        {
            "qr_code": qr_code,
            "merchant_transaction_id": merchant_transaction_id,
        },
    )
    return parse_payment(data)


async def qr_pay(transaction_id: str) -> Payment:
    """Проведение выплаты. Вызывается до expires_at из check."""
    data = await _request("POST", f"/v1/payments/qr/pay/{transaction_id}")
    return parse_payment(data)


async def transaction_status(transaction_id: str) -> Payment:
    data = await _request("GET", f"/v1/payments/{transaction_id}")
    return parse_payment(data)
