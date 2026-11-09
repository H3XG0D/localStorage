import { useEffect, useState } from "react";
import { formatRub } from "./casinoLevelCopy";

export const CASINO_CURRENCY_KEY = "focuspay_casino_currency";
export const CASINO_CURRENCY_EVENT = "focuspay-casino-currency";

export type CasinoCurrency = "rub" | "usdt";

export type WithdrawFeeParts = {
  feeRub: number | null;
  feeUsd: number | null;
};

export function readCasinoCurrency(): CasinoCurrency {
  try {
    return window.localStorage.getItem(CASINO_CURRENCY_KEY) === "usdt" ? "usdt" : "rub";
  } catch {
    return "rub";
  }
}

export function writeCasinoCurrency(next: CasinoCurrency): void {
  window.localStorage.setItem(CASINO_CURRENCY_KEY, next);
  window.dispatchEvent(new Event(CASINO_CURRENCY_EVENT));
}

export function formatUsdAmount(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function formatUsdtAmount(amountRub: number, usdtRub: number): string {
  return `${(amountRub / usdtRub).toFixed(2)} USDT`;
}

export function formatCasinoAmount(
  amountRub: number,
  currency: CasinoCurrency,
  usdtRub: number | null,
): string {
  if (currency === "usdt" && usdtRub != null && usdtRub > 0) {
    return formatUsdtAmount(amountRub, usdtRub);
  }
  return formatRub(amountRub);
}

export function formatFeeLabel(
  fee: WithdrawFeeParts,
  currency: CasinoCurrency,
  usdtRub: number | null,
): string {
  if (currency === "usdt") {
    if (fee.feeUsd != null && Number.isFinite(fee.feeUsd)) return `${fee.feeUsd.toFixed(2)} USDT`;
    if (fee.feeRub != null && usdtRub != null && usdtRub > 0) {
      return formatUsdtAmount(fee.feeRub, usdtRub);
    }
  }
  if (fee.feeRub != null && Number.isFinite(fee.feeRub)) return formatRub(fee.feeRub);
  if (fee.feeUsd != null && Number.isFinite(fee.feeUsd)) return formatUsdAmount(fee.feeUsd);
  return "—";
}

export function useCasinoCurrency(): {
  currency: CasinoCurrency;
  setCurrency: (next: CasinoCurrency) => void;
} {
  const [currency, setCurrencyState] = useState<CasinoCurrency>(() =>
    typeof window === "undefined" ? "rub" : readCasinoCurrency(),
  );
  useEffect(() => {
    setCurrencyState(readCasinoCurrency());
    const sync = () => setCurrencyState(readCasinoCurrency());
    window.addEventListener(CASINO_CURRENCY_EVENT, sync);
    return () => window.removeEventListener(CASINO_CURRENCY_EVENT, sync);
  }, []);
  function setCurrency(next: CasinoCurrency) {
    writeCasinoCurrency(next);
    setCurrencyState(next);
  }
  return { currency, setCurrency };
}
