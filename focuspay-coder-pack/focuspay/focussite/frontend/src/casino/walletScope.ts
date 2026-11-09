/**
 * Активная область кошелька казино: реальные рубли, бонусные фишки или турнир.
 *
 * Бэкенд — источник истины (`/user/casino/wallets`), локальное состояние нужно
 * только чтобы экраны успевали перерисоваться до ответа сервера.
 */
import { useCallback, useEffect, useState } from "react";

import {
  getCasinoWallets,
  setCasinoWallet,
  type CasinoWalletKind,
  type CasinoWalletRow,
  type CasinoWalletScopeInfo,
} from "../lib/public";

export const CASINO_WALLET_EVENT = "focuspay-casino-wallet";

export const REAL_SCOPE: CasinoWalletScopeInfo = {
  kind: "rub",
  scope: "rub",
  title: "Основной баланс",
  unit: "rub",
  tournament_id: null,
};

/**
 * `/user/casino/wallets` отдаёт активную область как `{wallet_kind, wallet_scope,
 * tournament_id, unit}` — без `kind`/`title`. Название берём из строки кошелька
 * (у турнира это его имя), иначе баннер печатает «undefined».
 */
export function normalizeActiveScope(
  active: Partial<CasinoWalletScopeInfo> & { wallet_kind?: string; wallet_scope?: string },
  wallets: CasinoWalletRow[],
): CasinoWalletScopeInfo {
  const kind = (active.kind || active.wallet_kind || REAL_SCOPE.kind) as CasinoWalletKind;
  const tournamentId = active.tournament_id ?? null;
  const scope = active.scope || active.wallet_scope || (tournamentId ? `trn:${tournamentId}` : kind);
  const row =
    wallets.find((item) => item.scope === scope) ??
    wallets.find((item) => item.selected) ??
    wallets.find((item) => item.kind === kind && (item.tournament_id ?? null) === tournamentId);
  const unit = active.unit || row?.unit || (kind === "rub" ? "rub" : "chips");
  const title = active.title || row?.title || (kind === "tournament" ? "Турнир" : REAL_SCOPE.title);
  return { kind, scope, title, unit, tournament_id: tournamentId };
}

export function walletRowBalance(row: CasinoWalletRow): number {
  if (row.unit === "chips") return Number(row.chips_balance || 0);
  return Number(row.available_rub || 0);
}

/** 1 фишка = 1.00, поэтому рубли и фишки форматируем одной функцией. */
export function formatWalletAmount(value: number, unit: "rub" | "chips"): string {
  const rounded = unit === "chips" ? Math.round(value) : Math.round(value * 100) / 100;
  const text = rounded.toLocaleString("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: unit === "chips" ? 0 : 2,
  });
  return unit === "chips" ? `${text} Ф` : `${text} ₽`;
}

export function walletUnitLabel(unit: "rub" | "chips"): string {
  return unit === "chips" ? "Ф" : "₽";
}

export function isChipsScope(scope: CasinoWalletScopeInfo | null | undefined): boolean {
  return scope?.unit === "chips";
}

export function notifyWalletChanged(): void {
  window.dispatchEvent(new Event(CASINO_WALLET_EVENT));
}

/**
 * Перезапрашивает данные экрана после смены кошелька: бэкенд отдаёт лобби
 * только своей области, поэтому старый список становится чужим.
 */
export function useWalletScopeRefresh(reload: () => void): void {
  useEffect(() => {
    const onEvent = () => reload();
    window.addEventListener(CASINO_WALLET_EVENT, onEvent);
    return () => window.removeEventListener(CASINO_WALLET_EVENT, onEvent);
  }, [reload]);
}

export type CasinoWalletState = {
  wallets: CasinoWalletRow[];
  active: CasinoWalletScopeInfo;
  loading: boolean;
  reload: () => Promise<void>;
  select: (kind: CasinoWalletKind, tournamentId?: number | null) => Promise<void>;
};

/**
 * Читает список кошельков и активную область. Любая смена области шлёт
 * `CASINO_WALLET_EVENT`, чтобы лобби и игровые экраны перезапросили данные.
 */
export function useCasinoWallet(enabled = true): CasinoWalletState {
  const [wallets, setWallets] = useState<CasinoWalletRow[]>([]);
  const [active, setActive] = useState<CasinoWalletScopeInfo>(REAL_SCOPE);
  const [loading, setLoading] = useState(enabled);

  const reload = useCallback(async () => {
    if (!enabled) return;
    try {
      const res = await getCasinoWallets();
      const rows = Array.isArray(res.wallets) ? res.wallets : [];
      setWallets(rows);
      setActive(res.active ? normalizeActiveScope(res.active, rows) : REAL_SCOPE);
    } catch {
      setWallets([]);
      setActive(REAL_SCOPE);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
    const onEvent = () => void reload();
    window.addEventListener(CASINO_WALLET_EVENT, onEvent);
    return () => window.removeEventListener(CASINO_WALLET_EVENT, onEvent);
  }, [reload]);

  const select = useCallback(
    async (kind: CasinoWalletKind, tournamentId: number | null = null) => {
      const res = await setCasinoWallet(kind, tournamentId);
      const rows = Array.isArray(res.wallets) ? res.wallets : [];
      setWallets(rows);
      setActive(res.active ? normalizeActiveScope(res.active, rows) : REAL_SCOPE);
      notifyWalletChanged();
    },
    [],
  );

  return { wallets, active, loading, reload, select };
}
