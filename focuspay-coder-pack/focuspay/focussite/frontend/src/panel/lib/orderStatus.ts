// Shared order-status labels + badge tones for the panel (from the panel API spec).
import type { BadgeTone } from "@/panel/ui/primitives";

export const STATUS_LABEL: Record<string, string> = {
  CREATED: "Создана",
  AWAITING_CHECK: "Ожидает чек",
  PENDING: "На проверке",
  COMPLETED: "Выполнена",
  PAID: "Оплачена",
  FAILED: "Ошибка",
  CANCELED: "Отменена",
  EXPIRED: "Истекла",
  DISPUTE: "Спор",
  OPERATOR_PENDING: "Ждёт оператора",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

export function orderStatusTone(status: string): BadgeTone {
  switch (status) {
    case "PAID":
    case "COMPLETED":
      return "green";
    case "AWAITING_CHECK":
    case "PENDING":
    case "OPERATOR_PENDING":
      return "yellow";
    case "CREATED":
      return "blue";
    case "DISPUTE":
      return "orange";
    case "FAILED":
    case "CANCELED":
    case "EXPIRED":
      return "red";
    default:
      return "default";
  }
}
