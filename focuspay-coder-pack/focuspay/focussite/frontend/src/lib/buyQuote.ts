import type { BuySpreadTier, RateEntry } from "@/lib/public";

export function resolveBuySpreadPct(
  baseRub: number,
  rate: RateEntry | undefined,
  tiers?: BuySpreadTier[] | null,
): number {
  const grid = Array.isArray(tiers) && tiers.length > 0
    ? [...tiers].sort((a, b) => Number(a.min_amount_rub) - Number(b.min_amount_rub))
    : null;
  if (grid && Number.isFinite(baseRub)) {
    let pct = Number(grid[0]?.pct);
    for (const row of grid) {
      const min = Number(row.min_amount_rub);
      if (Number.isFinite(min) && baseRub >= min) pct = Number(row.pct);
      else break;
    }
    if (Number.isFinite(pct)) return pct;
  }
  return Number(rate?.buy_commission_pct || 0);
}

export function buySpreadRangeLabel(tiers?: BuySpreadTier[] | null): string | null {
  if (!Array.isArray(tiers) || tiers.length < 2) return null;
  const pcts = tiers.map((row) => Number(row.pct)).filter((n) => Number.isFinite(n));
  if (pcts.length < 2) return null;
  const lo = Math.min(...pcts);
  const hi = Math.max(...pcts);
  if (lo === hi) return null;
  const fmt = (n: number) => String(n).replace(".", ",");
  return `${fmt(lo)}–${fmt(hi)}%`;
}

/** BUY + сумма в ₽: крипта по CoinGecko (`need`), оплата по Rapira × наценка. */
export function quoteBuyFromRub(
  baseRub: number,
  rate: RateEntry | undefined,
  tiers?: BuySpreadTier[] | null,
) {
  const need = Number(rate?.need || 0);
  const market = Number(rate?.market || 0);
  const pct = resolveBuySpreadPct(baseRub, rate, tiers);
  if (!(baseRub > 0) || !(need > 0) || !(market > 0)) return null;
  const crypto = baseRub / need;
  const pay = Math.ceil(crypto * market * (1 + pct / 100));
  return { crypto, pay, pct };
}

/** BUY + точная сумма монеты: объём не режется, к оплате = объём × курс × наценка. */
export function quoteBuyFromCrypto(
  cryptoAmount: number,
  rate: RateEntry | undefined,
  tiers?: BuySpreadTier[] | null,
) {
  const market = Number(rate?.market || 0);
  if (!(cryptoAmount > 0) || !(market > 0)) return null;
  const baseRub = cryptoAmount * market;
  const pct = resolveBuySpreadPct(baseRub, rate, tiers);
  const pay = Math.ceil(baseRub * (1 + pct / 100));
  return { crypto: cryptoAmount, pay, pct };
}
