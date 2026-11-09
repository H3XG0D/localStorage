"""Probe мерчанта: один create на полную сумму, fallback CARDRUB→SBPRUB."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from services.payin_resolver import (
    PayinPlan,
    _extract_bill,
    build_payin_plan,
    extract_merchant_uuid,
    get_bill_from_response,
)

logger = logging.getLogger("payin_discovery")

CreatePayinFn = Callable[..., Awaitable[dict]]
CancelPayinFn = Callable[[str], Awaitable[Any]]
GenerateOrderIdFn = Callable[[], str]

CARDRUB_TO_SBPRUB_MSG = "По карте реквизиты недоступны — оплата через СБП."
# One immediate check plus ten one-second waits gives Payfast about 10 seconds
# to finish assigning requisites before the operator fallback is used.
BILL_POLL_ATTEMPTS = 11
BILL_POLL_DELAY_SEC = 1.0


def _merge_bill(api_response: dict | None, bill: dict) -> dict:
    if not api_response:
        return {"bill": bill}
    merged = dict(api_response)
    merged["bill"] = bill
    return merged


async def _poll_bill(uuid_system: str) -> dict | None:
    from services.merchant_client import get_merchant_order

    for attempt in range(BILL_POLL_ATTEMPTS):
        if attempt:
            await asyncio.sleep(BILL_POLL_DELAY_SEC)
        try:
            order = await get_merchant_order(uuid_system)
        except Exception as e:
            logger.warning("get_order poll failed uuid=%s: %s", uuid_system, e)
            continue
        if order.get("status_pending") == "error":
            continue
        bill = get_bill_from_response(order)
        if bill:
            return bill
    return None


async def _response_with_bill(
    order_id: str,
    resp: dict | None,
    *,
    poll_bill: bool = True,
) -> tuple[str, dict | None]:
    if not resp or resp.get("status_pending") == "error":
        return order_id, None
    if _extract_bill(resp):
        return order_id, resp
    uuid_val = extract_merchant_uuid(resp)
    if not uuid_val:
        return order_id, resp
    if poll_bill:
        bill = await _poll_bill(uuid_val)
        if bill:
            return order_id, _merge_bill(resp, bill)
    return order_id, resp


@dataclass
class PayinDiscoveryResult:
    plan: PayinPlan
    probe_response: dict | None = None
    probe_order_id: str | None = None


async def _safe_cancel(cancel_fn: CancelPayinFn | None, api_response: dict | None) -> None:
    if not cancel_fn:
        return
    uuid_val = extract_merchant_uuid(api_response)
    if not uuid_val:
        return
    try:
        await cancel_fn(uuid_val)
    except Exception as e:
        logger.warning("probe cancel failed uuid=%s: %s", uuid_val, e)


async def _try_create(
    *,
    create_payin_fn: CreatePayinFn,
    generate_order_id_fn: GenerateOrderIdFn,
    user_id: int,
    amount: int,
    sub_token: str,
    poll_bill: bool = True,
) -> tuple[str, dict | None]:
    order_id = generate_order_id_fn()
    try:
        resp = await create_payin_fn(
            order_id=order_id,
            user_id=user_id,
            fiat_amount=amount,
            sub_token=sub_token,
        )
        if resp.get("status_pending") == "error":
            return order_id, None
        return await _response_with_bill(order_id, resp, poll_bill=poll_bill)
    except Exception as e:
        logger.warning("payin create failed sub=%s amount=%s: %s", sub_token, amount, e)
        return order_id, None


async def discover_payin_plan(
    *,
    fiat_amount: int,
    sub_token: str,
    user_id: int,
    create_payin_fn: CreatePayinFn,
    cancel_payin_fn: CancelPayinFn | None,
    generate_order_id_fn: GenerateOrderIdFn,
    poll_bill: bool = True,
) -> PayinDiscoveryResult:
    amount = int(fiat_amount)
    sub = (sub_token or "CARDRUB").upper()

    probe_id, probe_resp = await _try_create(
        create_payin_fn=create_payin_fn,
        generate_order_id_fn=generate_order_id_fn,
        user_id=user_id,
        amount=amount,
        sub_token=sub,
        poll_bill=poll_bill,
    )

    if _extract_bill(probe_resp):
        plan = build_payin_plan(amount, sub, api_response=probe_resp)
        return PayinDiscoveryResult(
            plan=plan,
            probe_response=probe_resp,
            probe_order_id=probe_id,
        )

    await _safe_cancel(cancel_payin_fn, probe_resp)

    if sub == "CARDRUB":
        sbp_id, sbp_resp = await _try_create(
            create_payin_fn=create_payin_fn,
            generate_order_id_fn=generate_order_id_fn,
            user_id=user_id,
            amount=amount,
            sub_token="SBPRUB",  # nosec B106
            poll_bill=poll_bill,
        )
        if _extract_bill(sbp_resp):
            plan = build_payin_plan(
                amount,
                "SBPRUB",  # nosec B106
                api_response=sbp_resp,
                resolved_sub_token="SBPRUB",  # nosec B106
            )
            plan.message = CARDRUB_TO_SBPRUB_MSG
            return PayinDiscoveryResult(
                plan=plan,
                probe_response=sbp_resp,
                probe_order_id=sbp_id,
            )
        await _safe_cancel(cancel_payin_fn, sbp_resp)

    plan = build_payin_plan(amount, sub, api_response=None)
    return PayinDiscoveryResult(plan=plan, probe_response=None, probe_order_id=None)
