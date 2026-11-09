// Web-order lifecycle for the public site (buyer scope). All calls require auth
// (bearer or cookie session); guest checkout is disabled server-side.
import { api } from "@/lib/api";
import type { CryptoId } from "@/lib/public";

export type Direction = "buy" | "sell";
export type SubToken = "SBPRUB" | "CARDRUB";

export type OrderStatus =
  | "CREATED"
  | "AWAITING_CHECK"
  | "PENDING"
  | "OPERATOR_PENDING"
  | "COMPLETED"
  | "PAID"
  | "FAILED"
  | "CANCELED"
  | "EXPIRED"
  | "DISPUTE";

export const STATUS_LABEL: Record<string, string> = {
  CREATED: "Создана",
  AWAITING_CHECK: "Ожидает чек",
  PENDING: "На проверке",
  OPERATOR_PENDING: "У оператора",
  COMPLETED: "Выполнена",
  PAID: "Выплачено",
  FAILED: "Ошибка",
  CANCELED: "Отменена",
  EXPIRED: "Истекла",
  DISPUTE: "Спор",
};

export const ACTIVE_STATUSES: OrderStatus[] = [
  "CREATED",
  "AWAITING_CHECK",
  "PENDING",
  "OPERATOR_PENDING",
  "COMPLETED",
];

export interface PaymentBuy {
  type: "buy";
  deposit_wallet?: string;
  bill?: Record<string, unknown>;
  pay_link?: string;
  fiat_amount?: number;
  parts_count?: number;
  part_index?: number;
  [key: string]: unknown;
}
export interface PaymentOperator {
  type: "operator";
  message?: string;
}
/** SELL на постоянный адрес приёма: клиент шлёт крипту сам. */
export interface PaymentDeposit {
  type: "deposit";
  deposit_wallet: string;
  message?: string;
}
export type Payment = PaymentBuy | PaymentOperator | PaymentDeposit | null;

export interface WalletConfirm {
  status: "pending" | "awaiting_address" | string;
  address: string;
  coin: string;
}

export interface Order {
  order_id: string;
  status: OrderStatus;
  direction: Direction;
  crypto: string; // e.g. "USDT_TRC20", "BTC"
  crypto_amount: number;
  fiat_amount: number;
  rate: number;
  requisites: string;
  created_at: string | null;
  expires_at: string | null;
  merchant_expires_at?: string | null;
  requisites_closed?: boolean;
  sub_token?: SubToken | null;
  required_receipt_type: number | null;
  deposit_wallet: string | null;
  payment: Payment;
  operator_message?: string;
  status_label?: string;
  crypto_confirmed?: boolean;
  payout_receipt_available?: boolean;
  payout_receipt_confirmed?: boolean;
  payout_tx_hash?: string | null;
  payout_explorer_url?: string | null;
  wallet_confirm?: WalletConfirm | null;
  order_source?: string;
  receipt_submitted?: boolean;
}

export interface CreateOrderInput {
  direction: Direction;
  crypto: CryptoId;
  network?: string | null;
  fiat_amount?: number | null;
  crypto_amount?: number | null;
  requisites: string;
  sub_token?: SubToken | null;
  plan_mode?: string | null;
  payin_round_up?: boolean;
}

export interface PayinPreview {
  mode: "single_candidate" | "reject" | string;
  parts: number[];
  pay_now: number;
  remainder_rub: number;
  message: string;
  has_bill: boolean;
  resolved_sub_token: string | null;
}

export interface PayinFitPreview {
  kind: "exact" | "round_up" | "as_quoted" | "none" | string;
  offer: boolean;
  offer_mode?: "none" | "silent" | "happy" | string;
  closes?: boolean;
  quote_rub: number;
  pay_rub: number;
  credit_rub: number;
  message?: string;
}

export const payinPreview = (fiat_amount: number, sub_token: SubToken = "SBPRUB") =>
  api<PayinPreview>("/public/orders/payin-preview", { method: "POST", body: { fiat_amount, sub_token } });

export const payinFit = (fiat_amount: number, sub_token: SubToken = "SBPRUB") =>
  api<PayinFitPreview>("/public/orders/payin-fit", { method: "POST", body: { fiat_amount, sub_token } });

/** Оффер доплаты до реквизита. Тот же текст, что бот показывает в чате. */
export function roundUpOffer(fit: PayinFitPreview | null | undefined): {
  mode: "happy" | "silent";
  payRub: number;
  creditRub: number;
  message: string;
} | null {
  if (!fit?.offer || (fit.offer_mode !== "happy" && fit.offer_mode !== "silent")) return null;
  const payRub = Number(fit.pay_rub);
  const creditRub = Number(fit.credit_rub);
  if (!Number.isFinite(payRub) || payRub <= 0 || !Number.isFinite(creditRub) || creditRub <= 0) return null;
  const pay = Math.round(payRub).toLocaleString("ru-RU");
  const credit = Math.round(creditRub).toLocaleString("ru-RU");
  const message = fit.offer_mode === "happy"
    ? `Счастливая сделка: к оплате ${pay} ₽ (−${credit} ₽). Разница на баланс после оплаты.`
    : `К оплате ${pay} ₽. Разница ${credit} ₽ вернётся на баланс после оплаты.`;
  return { mode: fit.offer_mode, payRub, creditRub, message };
}

export interface RequisiteRetryDraft {
  requisite_retry: true;
  saved?: boolean;
  ok?: boolean;
  reason?: "saved" | "empty" | "cooldown" | "expired" | "ready" | string;
  expires_at?: string | null;
  retry_after_sec?: number;
  attempt_count?: number;
  fiat_amount?: number;
  crypto?: string;
  sub_token?: string;
  message?: string;
  order_id?: string;
}

export function isRequisiteRetry(value: unknown): value is RequisiteRetryDraft {
  return Boolean(value && typeof value === "object" && (value as RequisiteRetryDraft).requisite_retry === true && !(value as RequisiteRetryDraft).order_id);
}

export const createOrder = (input: CreateOrderInput) =>
  api<Order | RequisiteRetryDraft>("/public/orders", { method: "POST", body: input });

export const retryRequisiteRequest = () =>
  api<Order | RequisiteRetryDraft>("/public/orders/requisite-retry", { method: "POST" });

export interface PayoutSent {
  order_id: string;
  coin: string;
  crypto_amount?: number | null;
  fiat_amount?: number | null;
  address?: string;
  txid?: string;
  explorer_url?: string;
}

export const getActiveOrder = () =>
  api<{ active: boolean; order?: Order; payout_sent?: PayoutSent | null }>("/public/orders/active", {
    method: "GET",
  });

export const submitWalletConfirm = (
  orderId: string,
  action: "confirm" | "replace",
  address?: string,
) =>
  api<{ ok: boolean; status: string; address?: string | null; detail?: string }>(
    `/public/orders/${encodeURIComponent(orderId)}/payout-wallet-confirm`,
    { method: "POST", body: { action, address } },
  );

export interface PayoutPushOption {
  eta_label: string;
  price_rub: number;
  fee_rate_sat_vb: number;
}

export interface PayoutTrack {
  visible: boolean;
  order_id?: string;
  coin?: string;
  crypto?: string;
  crypto_amount?: number | null;
  txid?: string;
  explorer_url?: string;
  confirmations?: number | null;
  confirmed?: boolean;
  confirmations_label?: string | null;
  eta_label?: string | null;
  can_push?: boolean;
  push_price_rub?: number | null;
  push_options?: PayoutPushOption[];
  push_reason?: string | null;
  push_pending?: boolean;
  push_pending_label?: string | null;
  available_rub?: number;
  shortfall_rub?: number;
}

export const getPayoutTrack = () =>
  api<PayoutTrack>("/public/orders/payout-track", { method: "GET" });

export const pushPayout = (orderId: string, quoteRub: number, feeRateSatVb?: number) =>
  api<{ ok: boolean; charged_rub: number; txid?: string; track?: PayoutTrack }>(
    `/public/orders/${orderId}/payout-push`,
    {
      method: "POST",
      body: {
        quote_rub: quoteRub,
        ...(feeRateSatVb && feeRateSatVb > 0 ? { fee_rate_sat_vb: feeRateSatVb } : {}),
      },
    },
  );

export const getOrder = (orderId: string) =>
  api<Order>(`/public/orders/${orderId}`, { method: "GET" });

export const confirmPaid = (orderId: string) =>
  api<{ status: string; requires_receipt?: boolean; required_receipt_type?: number }>(
    `/public/orders/${orderId}/confirm-paid`,
    { method: "POST" },
  );

export const cancelOrder = (orderId: string) =>
  api<{ status: string }>(`/public/orders/${orderId}/cancel`, { method: "POST" });

export const confirmPayoutReceipt = (orderId: string) =>
  api<{ ok?: boolean; already_confirmed?: boolean }>(`/public/orders/${orderId}/payout-receipt/confirm`, {
    method: "POST",
  });

export function uploadReceipt(orderId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return api<{ ok?: boolean; status?: string }>(`/public/orders/${orderId}/receipt`, {
    method: "POST",
    body: form,
  });
}

/** USDT symbols carry the network, e.g. "USDT_TRC20". Split for display. */
export function parseCryptoSymbol(sym: string): { base: string; network?: string } {
  const [base, network] = (sym || "").split("_");
  return { base: base || sym, network };
}
