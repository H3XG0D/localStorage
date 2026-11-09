export type LevelCopyRates = {
  index: number;
  cashback_percent: string;
  commission_complete_rate: string;
  commission_active_rate: string;
  remaining_wager_rub?: string;
  reach_bonus_rub?: string;
};

export type LevelCopyInput = {
  is_own?: boolean;
  level: LevelCopyRates;
  next_level: LevelCopyRates | null;
  own?: {
    commission_profile?: string;
    commission_rate?: string;
  };
};

export function formatRub(value: string | number): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(amount)} ₽`;
}

export function formatPct(value: string | number): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  return `${Number(amount.toFixed(2))}%`;
}

export function currentCommissionHeadline(data: LevelCopyInput): string {
  const rate = data.own?.commission_rate ?? data.level.commission_complete_rate;
  return `Комиссия сейчас ${formatPct(rate)}`;
}

export function levelCommissionPair(level: LevelCopyRates): string {
  return `Комиссия ${formatPct(level.commission_complete_rate)}`;
}

function commissionDrops(current: LevelCopyRates, next: LevelCopyRates): boolean {
  return Number(next.commission_complete_rate) < Number(current.commission_complete_rate);
}

export function nextLevelCopy(data: LevelCopyInput, opts?: { includeBonus?: boolean }): string {
  const includeBonus = opts?.includeBonus ?? Boolean(data.is_own);
  const next = data.next_level;
  if (!next) {
    const rate = data.own?.commission_rate ?? data.level.commission_complete_rate;
    return `Максимальный уровень. Комиссия ${formatPct(rate)}.`;
  }
  const rewards: string[] = [];
  if (commissionDrops(data.level, next)) {
    rewards.push(
      `комиссия ${formatPct(next.commission_complete_rate)} (сейчас ${formatPct(data.level.commission_complete_rate)})`,
    );
  }
  rewards.push(`кешбэк ${formatPct(next.cashback_percent)}`);
  const bonus = Number(next.reach_bonus_rub ?? 0);
  if (includeBonus && Number.isFinite(bonus) && bonus > 0) {
    rewards.push(`${formatRub(next.reach_bonus_rub ?? bonus)} на баланс`);
  }
  return `Ещё ${formatRub(next.remaining_wager_rub ?? 0)} оборота до уровня ${next.index}: ${rewards.join(", ")}`;
}

export function nextLevelTurnoverCopy(data: LevelCopyInput): string {
  const next = data.next_level;
  if (!next) return "Максимальный уровень";
  return `Ещё ${formatRub(next.remaining_wager_rub ?? 0)} оборота до уровня ${next.index}`;
}
