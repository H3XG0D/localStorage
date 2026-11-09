/** Range, gap, and cost helpers for casino volume-tier grids. API still stores only min. */

export type TierRangeRow = {
  min_wager_rub: string;
  max_wager_rub: string;
};

export function parseBound(raw: string): number | null {
  const text = raw.trim().replace(/\s/g, "").replace(",", ".");
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : Number.NaN;
}

export function formatRub(value: number): string {
  return `${value.toLocaleString("ru-RU")} ₽`;
}

export function formatPct(value: number): string {
  const rounded = Number((Math.round(value * 100) / 100).toFixed(2));
  return String(rounded).replace(".", ",");
}

export function attachDerivedMax<T extends TierRangeRow>(rows: T[]): T[] {
  return rows.map((row, index) => ({
    ...row,
    max_wager_rub: index + 1 < rows.length ? rows[index + 1].min_wager_rub : "",
  }));
}

export function applyUpperBound<T extends TierRangeRow>(rows: T[], index: number, maxValue: string): T[] {
  const next = rows.map((row) => ({ ...row }));
  next[index] = { ...next[index], max_wager_rub: maxValue };
  if (index + 1 < next.length && maxValue.trim()) {
    next[index + 1] = { ...next[index + 1], min_wager_rub: maxValue };
  }
  return next;
}

export function appendRangeRow<T extends TierRangeRow>(rows: T[], create: (min: string) => T): T[] {
  const next = rows.map((row) => ({ ...row }));
  const last = next[next.length - 1];
  if (last && !last.max_wager_rub.trim()) {
    last.max_wager_rub = last.min_wager_rub;
  }
  const min = last ? last.max_wager_rub || last.min_wager_rub || "0" : "0";
  next.push(create(min));
  return next;
}

export function insertRangeRow<T extends TierRangeRow>(rows: T[], index: number, create: (min: string) => T): T[] {
  const next = rows.map((row) => ({ ...row }));
  const source = next[index];
  if (source && !source.max_wager_rub.trim()) {
    next[index] = { ...source, max_wager_rub: source.min_wager_rub };
  }
  const min = next[index] ? next[index].max_wager_rub || next[index].min_wager_rub || "0" : "0";
  next.splice(index + 1, 0, create(min));
  return next;
}

export function removeRangeRow<T extends TierRangeRow>(rows: T[], index: number): T[] {
  if (index <= 0 || rows.length <= 1) return rows;
  const next = rows.filter((_, rowIndex) => rowIndex !== index);
  return attachDerivedMax(next);
}

export function cashbackTurnoverCost(percent: string): string {
  const value = parseBound(percent);
  if (value == null || Number.isNaN(value)) return "—";
  return `${formatPct(value)}% проигрыша`;
}

export function commissionTurnoverCost(active: string, complete: string): string {
  const activeValue = parseBound(active);
  const completeValue = parseBound(complete);
  if (activeValue == null || completeValue == null || Number.isNaN(activeValue) || Number.isNaN(completeValue)) {
    return "—";
  }
  return `${formatPct(activeValue / 2)}% / ${formatPct(completeValue / 2)}% оборота`;
}

export function tierRowError<T extends TierRangeRow>(rows: T[], index: number): string | null {
  const row = rows[index];
  if (!row) return null;
  const min = parseBound(row.min_wager_rub);
  const max = parseBound(row.max_wager_rub);
  if (row.min_wager_rub.trim() && Number.isNaN(min)) return "Нижняя граница: укажите число";
  if (row.max_wager_rub.trim() && Number.isNaN(max)) return "Верхняя граница: укажите число";
  if (min == null) return "Укажите нижнюю границу оборота";
  if (min < 0) return "Граница оборота не может быть отрицательной";
  if (index === 0 && min !== 0) return "Первая ступень должна начинаться с 0 ₽";
  if (index === rows.length - 1 && row.max_wager_rub.trim()) {
    return "Последняя ступень без верхней границы — она действует для любого оборота выше нижней";
  }
  if (max != null && !Number.isNaN(max) && max <= min) {
    return "Верхняя граница должна быть больше нижней";
  }

  if (index > 0) {
    const prev = rows[index - 1];
    const prevMin = parseBound(prev.min_wager_rub);
    const prevMax = parseBound(prev.max_wager_rub);
    if (prevMin != null && !Number.isNaN(prevMin) && min <= prevMin) {
      return "Нижняя граница должна быть строго больше предыдущей ступени";
    }
    if (prevMax == null) {
      return "У предыдущей ступени нет верхней границы — получится разрыв";
    }
    if (!Number.isNaN(prevMax) && min > prevMax) {
      return `Разрыв: тир кончается на ${formatRub(prevMax)}, следующий начинается с ${formatRub(min)}`;
    }
    if (!Number.isNaN(prevMax) && min < prevMax) {
      return `Пересечение: тир кончается на ${formatRub(prevMax)}, следующий начинается с ${formatRub(min)}`;
    }
  }

  if (index + 1 < rows.length && max == null) {
    return "Укажите верхнюю границу — от неё берётся начало следующей ступени";
  }
  return null;
}

export function collectTierErrors<T extends TierRangeRow>(
  rows: T[],
  idPrefix: string,
): Array<{ id: string; message: string }> {
  const errors: Array<{ id: string; message: string }> = [];
  if (!rows.length) {
    errors.push({ id: `${idPrefix}-0-min_wager_rub`, message: "Сетка не может быть пустой" });
    return errors;
  }
  const seen = new Set<number>();
  rows.forEach((row, index) => {
    const message = tierRowError(rows, index);
    if (message) errors.push({ id: `${idPrefix}-${index}-min_wager_rub`, message });
    const min = parseBound(row.min_wager_rub);
    if (min != null && !Number.isNaN(min)) {
      if (seen.has(min)) {
        errors.push({
          id: `${idPrefix}-${index}-min_wager_rub`,
          message: "Нижние границы ступеней не должны повторяться",
        });
      }
      seen.add(min);
    }
  });
  return errors;
}

function selfCheckTierGrid(): void {
  const gap = [
    { min_wager_rub: "0", max_wager_rub: "100000" },
    { min_wager_rub: "150000", max_wager_rub: "" },
  ];
  const gapMessage = tierRowError(gap, 1);
  if (!gapMessage || !gapMessage.includes("Разрыв") || !gapMessage.includes("100") || !gapMessage.includes("150")) {
    throw new Error("tierRowError: 100000→150000 must be a gap");
  }
  const overlap = [
    { min_wager_rub: "0", max_wager_rub: "150000" },
    { min_wager_rub: "100000", max_wager_rub: "" },
  ];
  const overlapMessage = tierRowError(overlap, 1);
  if (!overlapMessage || !overlapMessage.includes("Пересечение")) {
    throw new Error("tierRowError: overlapping ranges must error");
  }
  const ok = attachDerivedMax([
    { min_wager_rub: "0", max_wager_rub: "" },
    { min_wager_rub: "100000", max_wager_rub: "" },
  ]);
  if (ok[0].max_wager_rub !== "100000" || tierRowError(ok, 0) || tierRowError(ok, 1)) {
    throw new Error("contiguous 0–100000 must be valid");
  }
  const driven = applyUpperBound(ok, 0, "120000");
  if (driven[1].min_wager_rub !== "120000") {
    throw new Error("applyUpperBound must write the next min");
  }
  if (commissionTurnoverCost("15", "5") !== "7,5% / 2,5% оборота") {
    throw new Error("15%/5% commission must cost 7,5% / 2,5% of turnover");
  }
  if (cashbackTurnoverCost("5") !== "5% проигрыша") {
    throw new Error("5% cashback cost label drifted");
  }
}

selfCheckTierGrid();
