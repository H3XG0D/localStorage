"""Живой контекст FocusPay для Ops AI: курсы, спреды, тарифы (read-only)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ops_ai_live_context")

LIVE_RATES_DISCLAIMER = """## Важно (не цель задачи)
Этот блок — справочник курсов публичного API сайта (`/api/public/rates`).
Это НЕ экран `/exchange` и НЕ Telegram-бот.
Баг «курсы недоступны» в боте чинится в `bot/tg_bot_btc` (rates_api / exchange_flow).
Inbox `/ops/dev-requests` тоже не цель.
"""


def live_rates_not_a_target_note() -> str:
    """Короткий блок вместо полного снимка, когда задача не про сайт."""
    return (
        "# LIVE RATES / SETTINGS\n"
        + LIVE_RATES_DISCLAIMER
        + "\nСнимок курсов сайта не подключён: поверхность задачи не публичный /exchange."
    )


FORMULAS = """## Формулы FocusPay (как в проде)

Направления:
- BUY = клиент платит RUB/USDT → получает крипту (BTC/LTC/TRX/USDT)
- SELL = клиент отдаёт крипту → получает RUB

Курсы API `/api/public/rates`:
- market = рыночный RUB за 1 монету (Rapira; при сбое — frozen snapshot)
- need = CoinGecko RUB за 1 монету (оценка «сколько крипты нужно» при вводе в ₽)
- buy_rate = market × buy_markup   (клиент платит дороже)
- sell_rate = CoinGecko (Rapira fallback) × sell_multiplier
  discount: клиент получает меньше рынка; markup: доплачиваем за крипту

BUY, ввод в рублях (бот «в рублях» и сайт /exchange):
  crypto = base_rub / need
  pay_rub = crypto × market × buy_markup
  rate в ордере = market × buy_markup
  Если need недоступен — заявку не создавать.

BUY, ввод в монете:
  pay_rub ≈ crypto × buy_rate
  (как раньше, только Rapira)

BUY (сколько крипты за уже зафиксированный payin при rate ордера):
  crypto ≈ (fiat_rub + cashback_rub + discount_rub) / rate
  где rate в ордере = market × buy_markup (уже с наценкой). Не умножать markup повторно.

SELL:
  fiat_out ≈ crypto × sell_rate

Сеть: BTC mainnet, LTC mainnet, TRX/USDT TRC20. Комиссия сети — в тарифах ниже.
Не выдумывай цифры вне блока LIVE RATES. Если ордер конкретный — нужны order_id / направление.
"""


async def build_live_snapshot() -> str:
    """Снимок курсов и бизнес-настроек для промпта. Без секретов."""
    lines: list[str] = [
        "# LIVE RATES / SETTINGS (сейчас на сервере)",
        LIVE_RATES_DISCLAIMER,
        FORMULAS,
    ]
    try:
        import runtime_settings
        from commission import commission_percent
        from payment_methods_display import public_tariffs_data_async
        from routers.public import SUPPORTED

        await runtime_settings.refresh_settings()
        biz = runtime_settings.get_settings_sync()
        from routers import public as public_rates

        market = await public_rates.get_rates_cached()
        try:
            sell_market = await public_rates.get_sell_market_rates()
        except Exception:
            sell_market = market if isinstance(market, dict) else {}
        source = str(getattr(public_rates, "_cache", {}).get("_source") or "rapira_or_cache")

        buy_m = runtime_settings.buy_markup(manual=False)
        buy_man = runtime_settings.buy_markup(manual=True)
        sell_d = runtime_settings.sell_discount()

        lines.append("## Спреды (runtime)")
        lines.append(
            f"- buy_markup auto={buy_m:.4f} ({biz.get('buy_spread_auto_pct')}%), "
            f"manual={buy_man:.4f} ({biz.get('buy_spread_manual_pct')}%)"
        )
        lines.append(
            f"- sell_multiplier={sell_d:.4f} (mode {biz.get('sell_pricing_mode')}, "
            f"spread {biz.get('sell_spread_pct')}%, markup {biz.get('sell_markup_pct')}%)"
        )
        lines.append(
            f"- card_fee auto={biz.get('card_fee_auto_pct')}%, "
            f"manual={biz.get('card_fee_manual_pct')}%"
        )
        lines.append(f"- rates_source≈{source}")

        lines.append("## Курсы RUB за 1 монету")
        lines.append("| coin | market | buy | sell | buy% | sell% |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for crypto in SUPPORTED:
            price = market.get(crypto) if isinstance(market, dict) else None
            if price is None:
                continue
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            buy = p * buy_m
            sell_p = float(sell_market.get(crypto) or p)
            sell = sell_p * sell_d
            lines.append(
                f"| {crypto.upper()} | {p:.2f} | {buy:.2f} | {sell:.2f} | "
                f"{commission_percent(crypto, 'buy'):.1f} | "
                f"{commission_percent(crypto, 'sell'):.1f} |"
            )

        try:
            tariffs = await public_tariffs_data_async()
            lines.append("## Публичные тарифы / лимиты / сеть")
            lines.append(_compact_jsonish(tariffs))
        except Exception as e:
            logger.warning("tariffs for ops_ai: %s", e)
            lines.append(f"(тарифы недоступны: {e})")
    except Exception as e:
        logger.warning("live snapshot failed: %s", e)
        lines.append(f"LIVE snapshot недоступен: {e}")
        lines.append("Отвечай по docs/RAG; не выдумывай курсы.")
    return "\n".join(lines)


def _compact_jsonish(data: Any, *, max_chars: int = 3500) -> str:
    import json

    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n… (truncated)"
    return text
