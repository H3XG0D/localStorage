import { TierGridEditor } from "@/panel/ui/TierGridEditor";
import {
  attachDerivedMax,
  cashbackTurnoverCost,
  collectTierErrors,
  commissionTurnoverCost,
  parseBound,
  tierRowError,
} from "@/panel/ui/tierGridModel";
import {
  formatLevelShares,
  formatShareBreakdown,
  scaledSharesForProfile,
  type CommissionShareBase,
} from "@/panel/admin/Casino/casinoSettingsModel";

export interface CashbackTierRow {
  min_wager_rub: string;
  max_wager_rub: string;
  percent: string;
}

export interface CommissionTierRow {
  min_wager_rub: string;
  max_wager_rub: string;
  active_rate: string;
  complete_rate: string;
}

export interface BonusRow {
  min_wager_rub: string;
  bonus_rub: string;
}

export interface CasinoLevelRow {
  min_wager_rub: string;
  max_wager_rub: string;
  percent: string;
  active_rate: string;
  complete_rate: string;
  reach_bonus_rub: string;
}

function num(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function lastAtOrBelow<T extends { min_wager_rub: string }>(rows: T[], min: number): T | undefined {
  let found: T | undefined;
  for (const row of rows) {
    const threshold = num(row.min_wager_rub);
    if (!Number.isNaN(threshold) && threshold <= min) found = row;
  }
  return found;
}

export function bonusesFromApi(rows: Array<{ min_wager_rub: number; bonus_rub: number }> | undefined): BonusRow[] {
  if (!rows?.length) return [];
  return rows.map((row) => ({
    min_wager_rub: String(row.min_wager_rub),
    bonus_rub: String(row.bonus_rub),
  }));
}

export function parseBonusesForSave(rows: BonusRow[]) {
  return rows
    .filter((row) => num(row.min_wager_rub) > 0 && num(row.bonus_rub) > 0)
    .map((row) => ({
      min_wager_rub: Number(row.min_wager_rub),
      bonus_rub: Number(row.bonus_rub),
    }));
}

export function mergeLevels(
  cashback: CashbackTierRow[],
  commission: CommissionTierRow[],
  bonuses: BonusRow[],
): CasinoLevelRow[] {
  const mins = new Set<number>();
  for (const row of [...cashback, ...commission, ...bonuses]) {
    const value = num(row.min_wager_rub);
    if (!Number.isNaN(value) && value >= 0) mins.add(value);
  }
  if (!mins.size) mins.add(0);
  const sorted = [...mins].sort((left, right) => left - right);
  const merged = sorted.map((min) => {
    const cash = lastAtOrBelow(cashback, min);
    const comm = lastAtOrBelow(commission, min);
    const bonus = bonuses.find((row) => num(row.min_wager_rub) === min);
    return {
      min_wager_rub: String(min),
      max_wager_rub: "",
      percent: cash?.percent ?? "2",
      active_rate: comm?.active_rate ?? "15",
      complete_rate: comm?.complete_rate ?? "5",
      reach_bonus_rub: min > 0 ? bonus?.bonus_rub ?? "0" : "0",
    };
  });
  return attachDerivedMax(merged);
}

export function splitLevels(rows: CasinoLevelRow[]): {
  cashback: CashbackTierRow[];
  commission: CommissionTierRow[];
  bonuses: BonusRow[];
} {
  const withMax = attachDerivedMax(rows);
  return {
    cashback: withMax.map((row) => ({
      min_wager_rub: row.min_wager_rub,
      max_wager_rub: row.max_wager_rub,
      percent: row.percent,
    })),
    commission: withMax.map((row) => ({
      min_wager_rub: row.min_wager_rub,
      max_wager_rub: row.max_wager_rub,
      active_rate: row.active_rate,
      complete_rate: row.complete_rate,
    })),
    bonuses: withMax
      .filter((row) => num(row.min_wager_rub) > 0 && num(row.reach_bonus_rub) > 0)
      .map((row) => ({ min_wager_rub: row.min_wager_rub, bonus_rub: row.reach_bonus_rub })),
  };
}

function emptyCashbackRow(min: string): CashbackTierRow {
  return { min_wager_rub: min, max_wager_rub: "", percent: "2" };
}

function emptyCommissionRow(min: string): CommissionTierRow {
  return { min_wager_rub: min, max_wager_rub: "", active_rate: "15", complete_rate: "5" };
}

export function cashbackTiersFromApi(
  rows: Array<{ min_wager_rub: number; percent: number }> | undefined,
): CashbackTierRow[] {
  if (!rows?.length) return [emptyCashbackRow("0")];
  return attachDerivedMax(
    rows.map((row) => ({
      min_wager_rub: String(row.min_wager_rub),
      max_wager_rub: "",
      percent: String(row.percent),
    })),
  );
}

export function commissionTiersFromApi(
  rows: Array<{ min_wager_rub: number; active_rate: number; complete_rate: number }> | undefined,
): CommissionTierRow[] {
  if (!rows?.length) return [emptyCommissionRow("0")];
  return attachDerivedMax(
    rows.map((row) => ({
      min_wager_rub: String(row.min_wager_rub),
      max_wager_rub: "",
      active_rate: String(row.active_rate),
      complete_rate: String(row.complete_rate),
    })),
  );
}

export function parseCashbackTiersForSave(rows: CashbackTierRow[]) {
  return rows.map((row) => ({
    min_wager_rub: Number(row.min_wager_rub),
    percent: Number(row.percent),
  }));
}

export function parseCommissionTiersForSave(rows: CommissionTierRow[]) {
  return rows.map((row) => ({
    min_wager_rub: Number(row.min_wager_rub),
    active_rate: Number(row.active_rate),
    complete_rate: Number(row.complete_rate),
  }));
}

export function cashbackTierErrors(rows: CashbackTierRow[]) {
  const errors = collectTierErrors(rows, "tier-cashback");
  rows.forEach((row, index) => {
    const percent = parseBound(row.percent);
    if (percent == null || Number.isNaN(percent) || percent < 0 || percent > 100) {
      errors.push({
        id: `tier-cashback-${index}-percent`,
        message: `Кешбек ступени ${index + 1}: процент от 0 до 100`,
      });
    }
  });
  return errors;
}

export function commissionTierErrors(rows: CommissionTierRow[]) {
  const errors = collectTierErrors(rows, "tier-commission");
  rows.forEach((row, index) => {
    const active = parseBound(row.active_rate);
    const complete = parseBound(row.complete_rate);
    if (active == null || Number.isNaN(active) || active < 0 || active > 100) {
      errors.push({
        id: `tier-commission-${index}-active_rate`,
        message: `Комиссия ступени ${index + 1}: «до отыгрыша» от 0 до 100`,
      });
    }
    if (complete == null || Number.isNaN(complete) || complete < 0 || complete > 100) {
      errors.push({
        id: `tier-commission-${index}-complete_rate`,
        message: `Комиссия ступени ${index + 1}: «после» от 0 до 100`,
      });
    }
    if (
      active != null &&
      complete != null &&
      !Number.isNaN(active) &&
      !Number.isNaN(complete) &&
      complete > active
    ) {
      errors.push({
        id: `tier-commission-${index}-complete_rate`,
        message: `Комиссия ступени ${index + 1}: ставка после отыгрыша не может быть выше ставки до отыгрыша`,
      });
    }
  });
  return errors;
}

interface CasinoTierGridsProps {
  cashbackTiers: CashbackTierRow[];
  commissionTiers: CommissionTierRow[];
  bonusRows: BonusRow[];
  shareBase: CommissionShareBase;
  disabled?: boolean;
  onCashbackChange: (rows: CashbackTierRow[]) => void;
  onCommissionChange: (rows: CommissionTierRow[]) => void;
  onBonusChange: (rows: BonusRow[]) => void;
}

export function CasinoTierGrids({
  cashbackTiers,
  commissionTiers,
  bonusRows,
  shareBase,
  disabled,
  onCashbackChange,
  onCommissionChange,
  onBonusChange,
}: CasinoTierGridsProps) {
  const levels = mergeLevels(cashbackTiers, commissionTiers, bonusRows);

  function emit(next: CasinoLevelRow[]) {
    const split = splitLevels(next);
    onCashbackChange(split.cashback);
    onCommissionChange(split.commission);
    onBonusChange(split.bonuses);
  }

  return (
    <div className="flex flex-col gap-5">
      <TierGridEditor
        title="Уровни по недельному обороту"
        description="Неделя Москва. Порог оборота задаёт уровень: кешбэк %, комиссия до/после отыгрыша, разовый бонус. Первая строка = 0 ₽ и те же комиссии, что в блоке «Комиссия и доли». Creator / L1 / L2 дальше режутся пропорционально. Нажмите ячейку — пояснение под таблицей."
        rows={levels}
        idPrefix="tier-level"
        columns={[
          { key: "min_wager_rub", label: "От (₽)", lockFirst: true },
          { key: "max_wager_rub", label: "До (₽)", drivesNextMin: true, placeholder: "∞" },
          { key: "percent", label: "Кешбэк (%)", min: 0, max: 100, step: "0.01" },
          { key: "active_rate", label: "Комиссия до (%)", min: 0, max: 100, step: "0.01" },
          { key: "complete_rate", label: "Комиссия после (%)", min: 0, max: 100, step: "0.01" },
          { key: "reach_bonus_rub", label: "Бонус (₽)", min: 0, lockFirst: true },
        ]}
        computed={[
          {
            key: "cost",
            label: "Во что обходится",
            render: (row) =>
              `${cashbackTurnoverCost(row.percent)} · ${commissionTurnoverCost(row.active_rate, row.complete_rate)}`,
          },
          {
            key: "shares_active",
            label: "Доли до",
            render: (row) =>
              formatLevelShares(scaledSharesForProfile(shareBase, "wagering_active", row.active_rate)),
          },
          {
            key: "shares_complete",
            label: "Доли после",
            render: (row) =>
              formatLevelShares(scaledSharesForProfile(shareBase, "wagering_complete", row.complete_rate)),
          },
        ]}
        disabled={disabled}
        emptyRow={(min) => {
          const last = levels[levels.length - 1];
          return {
            min_wager_rub: min,
            max_wager_rub: "",
            percent: last?.percent ?? "2",
            active_rate: last?.active_rate ?? "15",
            complete_rate: last?.complete_rate ?? "5",
            reach_bonus_rub: "0",
          };
        }}
        onChange={emit}
        addLabel="Добавить уровень"
        rowError={(_row, index, rows) => tierRowError(rows, index)}
        renderPanel={({ column, row }) => {
          if (column.key === "reach_bonus_rub") {
            return (
              <p>
                Разовый кредит на баланс, когда недельный оборот впервые пересекает этот порог. 0 = не начислять. Один раз за
                игрока × неделю × порог.
              </p>
            );
          }
          if (column.key === "percent") {
            return <p>Кешбек — доля учтённого проигрыша, не оборота ставок.</p>;
          }
          if (column.key === "active_rate" || column.key === "complete_rate") {
            return <p>Комиссия берётся с проигравшей ставки. «После» не может быть выше «до».</p>;
          }
          const computedKey = String(column.key);
          if (computedKey === "shares_active" || computedKey === "shares_complete") {
            const profile = computedKey === "shares_active" ? "wagering_active" : "wagering_complete";
            const rate = computedKey === "shares_active" ? row.active_rate : row.complete_rate;
            const shares = scaledSharesForProfile(shareBase, profile, rate);
            if (!shares) {
              return <p>Доли не считаются: проверьте комиссию и Creator/L1/L2 в блоке «Комиссия и доли».</p>;
            }
            return (
              <p>
                {formatShareBreakdown(shares)}. Порядок: Creator, реферал L1, реферал L2, казино. На первой ступени совпадают
                с полями выше; дальше × комиссия ступени / комиссия первой ступени.
              </p>
            );
          }
          return <p>Правое число «До» подставляет «От» следующей строки. Разрыв и пересечение подсвечиваются сразу.</p>;
        }}
      />
    </div>
  );
}
