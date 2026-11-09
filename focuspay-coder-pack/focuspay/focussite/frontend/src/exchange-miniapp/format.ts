export function rub(value: number | string | null | undefined, digits = 2) {
  const amount = Number(value ?? 0);
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number.isFinite(amount) ? amount : 0);
}

export function rateRub(value: number | null | undefined) {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount) || amount <= 0) return "—";
  const digits = amount >= 1000 ? 0 : 2;
  return rub(amount, digits);
}

export function coin(value: number | string | null | undefined) {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount)) return "0";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 6 }).format(amount);
}

const STATUS_TEXT: Record<string, string> = {
  CREATED: "Ждём оплату",
  AWAITING_CHECK: "На проверке",
  PENDING: "На проверке",
  OPERATOR_PENDING: "У оператора",
  COMPLETED: "Выплачено",
  PAID: "Выплачено",
  FAILED: "Ошибка",
  CANCELED: "Отменена",
  EXPIRED: "Истекла",
  DISPUTE: "Спор",
};

export function orderStatusText(status: string, label?: string | null) {
  return label || STATUS_TEXT[status] || status;
}
