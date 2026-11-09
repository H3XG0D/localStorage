export type FillAllocation = { status?: string; amount_rub?: number };

export function fillTank(opts: {
  amountRub: number;
  paidRub: number;
  reservedRub?: number | null;
  freeRub?: number | null;
  allocations?: FillAllocation[];
}) {
  const amount = Number.isFinite(opts.amountRub) ? Math.max(0, opts.amountRub) : 0;
  const paid = Number.isFinite(opts.paidRub) ? Math.max(0, opts.paidRub) : 0;
  const fromAlloc =
    Array.isArray(opts.allocations) && opts.allocations.length > 0
      ? opts.allocations
          .filter((a) => a.status === "RESERVED")
          .reduce((sum, a) => sum + Number(a.amount_rub || 0), 0)
      : null;
  const reservedRaw = fromAlloc != null ? fromAlloc : opts.reservedRub;
  const reservedN = Number.isFinite(Number(reservedRaw)) ? Math.max(0, Number(reservedRaw)) : 0;
  let free = opts.freeRub;
  if (free == null || fromAlloc != null) {
    free = Math.max(0, amount - paid - reservedN);
  }
  const freeN = Number.isFinite(Number(free)) ? Math.max(0, Number(free)) : 0;
  return { amount, paid, reserved: reservedN, free: freeN };
}
