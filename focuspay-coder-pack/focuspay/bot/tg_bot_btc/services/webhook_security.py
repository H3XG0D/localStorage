"""Проверки безопасности webhook (без зависимости от FastAPI/БД)."""
import hashlib
import hmac
import ipaddress
import time
from decimal import Decimal, InvalidOperation

from services import config_rates

WEBHOOK_SIGNATURE_MAX_AGE_SEC = 300

PAYABLE_STATUSES = frozenset({"CREATED", "PENDING", "AWAITING_CHECK"})
# COMPLETED только из PENDING: чек принят мерчантом (AWAITING_CHECK -> PENDING).
# AWAITING_CHECK не завершаем — иначе крипта уходит, когда чек не долетел.
WEBHOOK_COMPLETABLE_STATUSES = frozenset({"PENDING"})
AMOUNT_TOLERANCE_RUB = Decimal("1")

PAYMENT_SUCCESS_MARKERS = frozenset(
    {"COMPLETED", "SUCCESS", "SUCCSES", "PAID"}
)

PAYFAST_FAIL_STATUSES = frozenset(
    {"ERROR", "FAILED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}
)


def _webhook_signing_secret() -> str:
    merchant = getattr(config_rates, "MERCHANT", None) or {}
    return (
        (merchant.get("secret_key") or "").strip()
        or (getattr(config_rates, "WEBHOOK_SECRET", "") or "").strip()
    )


def sign_webhook_body(body_bytes: bytes, timestamp: str | None = None) -> tuple[str, str]:
    """HMAC подпись тела (timestamp + body), как у исходящих запросов к мерчанту."""
    secret = _webhook_signing_secret()
    if not secret:
        return "", timestamp or ""
    ts = timestamp or str(int(time.time()))
    message = ts + body_bytes.decode("utf-8")
    sig = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return sig, ts


def verify_webhook_signature(
    body_bytes: bytes,
    signature: str | None,
    timestamp: str | None,
) -> bool:
    secret = _webhook_signing_secret()
    if not secret or not signature or not timestamp:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > WEBHOOK_SIGNATURE_MAX_AGE_SEC:
        return False
    message = str(ts) + body_bytes.decode("utf-8")
    expected = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def sign_finance666_webhook(
    secret: str,
    webhook_id: str,
    timestamp: str,
    body_bytes: bytes,
) -> str:
    """Подпись finance666: HMAC-SHA256 от "{id}.{ts}." + сырое тело, ключ — секрет целиком."""
    message = f"{webhook_id}.{timestamp}.".encode("utf-8") + body_bytes
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_finance666_webhook(
    body_bytes: bytes,
    *,
    webhook_id: str | None,
    timestamp: str | None,
    signature: str | None,
    secret: str | None = None,
) -> bool:
    """Тело берётся байт в байт: пересобранный JSON подпись не пройдёт."""
    if secret is None:
        secret = (getattr(config_rates, "FINANCE666_WEBHOOK_SECRET", "") or "").strip()
    if not secret or not webhook_id or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > WEBHOOK_SIGNATURE_MAX_AGE_SEC:
        return False
    expected = sign_finance666_webhook(secret, webhook_id, str(timestamp), body_bytes)
    return hmac.compare_digest(expected, signature.strip().lower())


def _configured_networks(name: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = getattr(config_rates, name, "") or ""
    networks = []
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _ip_in_networks(
    value: str | None,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    if not value:
        return False
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return any(address in network for network in networks)


def resolve_client_ip(
    direct_host: str | None,
    *,
    cf_connecting_ip: str | None = None,
    real_ip: str | None = None,
    forwarded_for: str | None = None,
) -> str | None:
    """Use forwarded client headers only when the direct peer is trusted."""
    trusted = _configured_networks("WEBHOOK_TRUSTED_PROXIES")
    if not trusted:
        trusted = (
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("::1/128"),
        )
    if not _ip_in_networks(direct_host, trusted):
        return direct_host

    for candidate in (cf_connecting_ip, real_ip):
        if candidate and candidate.strip():
            return candidate.strip()
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return direct_host


def verify_webhook_client_ip(client_host: str | None) -> bool:
    """Проверка IP webhook клиента по whitelist.

    Payfast не раскрывает свои egress-IP, поэтому пустая whitelist означает
    «IP-фильтр выключен»: полагаемся на подписи (api_key в теле / HMAC).
    Если WEBHOOK_ALLOWED_IPS задан — фильтруем строго по нему.
    """
    import logging

    raw = getattr(config_rates, "WEBHOOK_ALLOWED_IPS", "") or ""
    if not raw.strip():
        logging.getLogger("webhook_server").warning(
            "WEBHOOK_ALLOWED_IPS is not set — IP filter disabled, "
            "callbacks authenticated by signature only"
        )
        return True
    if not client_host:
        return False
    return _ip_in_networks(client_host, _configured_networks("WEBHOOK_ALLOWED_IPS"))


def verify_payfast_callback(body: dict) -> bool:
    """Payfast §6.2: api_key и id_merchant в JSON-теле callback (без HMAC-заголовков)."""
    if not isinstance(body, dict):
        return False
    merchant = getattr(config_rates, "MERCHANT", None) or {}
    expected_key = (merchant.get("api_key") or "").strip()
    if not expected_key:
        return False
    got_key = body.get("api_key")
    if got_key is None or not hmac.compare_digest(str(got_key).strip(), expected_key):
        return False
    expected_id = merchant.get("merchant_id")
    if expected_id is not None and str(expected_id).strip() != "":
        try:
            if int(body.get("id_merchant")) != int(expected_id):
                return False
        except (TypeError, ValueError):
            return False
    return True


def verify_incoming_webhook(
    body_bytes: bytes,
    body: dict,
    signature: str | None,
    timestamp: str | None,
) -> bool:
    """Payfast callback (тело) или legacy HMAC (заголовки, симулятор)."""
    if verify_payfast_callback(body):
        return True
    if signature and timestamp:
        return verify_webhook_signature(body_bytes, signature, timestamp)
    return False


def is_payment_success_payload(
    status: str | None,
    status_pending,
    status_check,
    direction: str | None = None,
    status_file=None,
) -> bool:
    """Webhook-триггер «возможно оплата подтверждена» — перед COMPLETED сверяем /get_order.

    Payfast: только SUCCSES/SUCCESS/COMPLETED. PAID+status_file=0 — не апрув.
    status_check=1 — «доп. чек не запрошен» (§3.4), не подтверждение оплаты.
  """
    from services.payfast_payin_guard import is_payfast_settled

    st = str(status or "").strip().upper() if status is not None else ""
    if st and st in PAYFAST_FAIL_STATUSES:
        return False

    if (direction or "").lower() == "buy":
        return is_payfast_settled(st or None, status_file)

    if is_payfast_settled(st or None, status_file):
        return True
    if st and st in PAYMENT_SUCCESS_MARKERS:
        return True
    return False


def order_ready_for_merchant_complete(order: dict) -> tuple[bool, str | None]:
    direction = (order.get("direction") or "buy").lower()
    status = str(order.get("status") or "")
    if direction != "buy":
        return False, "not_buy_order"
    if status == "AWAITING_CHECK":
        return False, "receipt_not_submitted"
    if status not in WEBHOOK_COMPLETABLE_STATUSES:
        return False, f"buy_awaiting_payment_proof ({status})"
    return True, None


RECEIPT_URL_TTL_SEC = int(getattr(config_rates, "RECEIPT_URL_TTL_SEC", 0) or 30 * 24 * 3600)


def sign_receipt_access(filename: str, exp: int | None = None) -> str:
    secret = getattr(config_rates, "RECEIPT_SECRET", "") or getattr(
        config_rates, "WEBHOOK_SECRET", ""
    )
    if not secret:
        return ""
    # exp задаёт срок действия ссылки (TTL); legacy-ссылки без exp подписывают имя.
    payload = f"{filename}:{exp}" if exp is not None else filename
    return hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]


def verify_receipt_access(filename: str, signature: str, exp: str | int | None = None) -> bool:
    if not signature:
        return False
    if exp is not None and str(exp).strip() != "":
        try:
            exp_int = int(exp)
        except (TypeError, ValueError):
            return False
        if time.time() > exp_int:
            return False  # ссылка просрочена
        expected = sign_receipt_access(filename, exp_int)
    else:
        expected = sign_receipt_access(filename)
    if not expected:
        return False
    return hmac.compare_digest(expected, signature)


def amount_matches_order(data_order: dict, order: dict) -> tuple[bool, str | None]:
    raw = data_order.get("amount")
    if raw is None:
        return False, "missing_amount"
    try:
        paid = Decimal(str(raw))
        expected = Decimal(str(order.get("fiat_amount") or 0))
    except (InvalidOperation, TypeError, ValueError):
        return False, "invalid_amount"
    if not paid.is_finite() or not expected.is_finite():
        return False, "invalid_amount"
    if abs(paid - expected) > AMOUNT_TOLERANCE_RUB:
        return False, f"amount_mismatch paid={paid} expected={expected}"
    return True, None
