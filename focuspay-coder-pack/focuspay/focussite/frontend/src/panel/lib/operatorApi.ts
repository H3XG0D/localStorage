// Operator panel API. All calls scope="operator". Types are intentionally loose
// (known fields + index signature) — the backend returns rich rows and we render
// defensively. Contract mirrors routers/operator.py.
import { getPanelToken, PanelApiError, panelApi } from "@/panel/lib/panelApi";
import type { CasinoClientHistoryPage, CasinoClientProfile } from "@/panel/lib/casinoClientProfile";

const op = <T>(path: string, opts: Omit<Parameters<typeof panelApi>[1], "scope"> = {}) =>
  panelApi<T>(`/operator${path}`, { ...opts, scope: "operator" });

export interface HotWalletCoin {
  coin?: string;
  spendable?: number;
  unconfirmed?: number;
  value_rub?: number;
  hours_phrase?: string;
  deposit_address?: string | null;
  [k: string]: unknown;
}
export interface HotWalletView {
  available?: boolean;
  below_floor?: boolean;
  floor_phrase?: string;
  total_rub?: number;
  coins?: HotWalletCoin[];
  [k: string]: unknown;
}
export interface OperatorMe {
  operator: { id: number; username?: string; display_name?: string; operator_role?: string; operator_roles?: string[]; role_grades?: Record<string, string>; avatar_url?: string; [k: string]: unknown };
  active_shift: ShiftRow | null;
  shift_balances: ShiftBalance[];
  queue_count: number;
  active_work_count: number;
  current_shift: Record<string, unknown> | null;
  team_on_shift: TeamMember[];
  on_shift_count: number;
  today: { orders_count: number; fiat_total: number };
}
export interface ShiftRow {
  id: number;
  operator_id?: number;
  started_at?: string;
  ended_at?: string | null;
  note?: string | null;
  [k: string]: unknown;
}
export interface ShiftBalance {
  crypto?: string;
  amount?: number;
  balance_start?: number | null;
  balance_end?: number | null;
  [k: string]: unknown;
}
export interface TeamMember {
  id?: number;
  username?: string;
  display_name?: string;
  operator_roles?: string[];
  role_grades?: Record<string, string>;
  on_shift?: boolean;
  [k: string]: unknown;
}

export interface OrderRow {
  id?: number;
  order_id: string;
  user_id?: number;
  buyer_username?: string;
  buyer_first_name?: string;
  status: string;
  status_label?: string;
  direction: string;
  crypto: string;
  crypto_amount?: number;
  fiat_amount?: number;
  rate?: number;
  requisites?: string;
  wallet_address?: string;
  network?: string;
  payout_tx_hash?: string | null;
  sub_token?: string;
  origin?: string;
  order_source?: string;
  source_label?: string;
  operator_id?: number | null;
  operator_name?: string;
  assigned_operator?: { id?: number; display_name?: string; username?: string } | null;
  assigned_to_me?: boolean;
  has_receipt?: boolean;
  created_at?: string;
  updated_at?: string;
  expires_at?: string;
  crypto_confirmed_at?: string | null;
  payin_requisite_id?: number | null;
  live_requisites?: boolean;
  payout_rail?: {
    stage?: string;
    allocation_status?: string | null;
    has_receipt?: boolean;
    client_confirmed?: boolean;
    client_confirmed_at?: string | null;
    requisite_id?: number | null;
    amount_rub?: number | null;
  } | null;
  hold_reason?: string;
  hold_reason_label?: string;
  replaced_by_order_id?: string | null;
  required_receipt_type?: number;
  receipt_ops_pending?: boolean;
  payfast_id?: string | null;
  can_send_receipt_to_payfast?: boolean;
  wallet_confirm_ops?: {
    stage?: "waiting_timer" | "asked" | "confirmed" | string;
    status?: string;
    coin?: string;
    address?: string;
    confirmed_at?: string | null;
    send_at?: string | null;
    seconds_left?: number;
    delay_sec?: number;
    can_send_early?: boolean;
  } | null;
  [k: string]: unknown;
}

export interface QueueSummary {
  queue_count: number;
  ready_to_accept_count?: number;
  awaiting_receipt_count?: number;
  client_hold_count?: number;
  withdrawal_incoming_count?: number;
  exchange_incoming_count?: number;
  in_progress_count: number;
  in_progress_orders: OrderRow[];
  in_progress_withdrawals: Record<string, unknown>[];
  [k: string]: unknown;
}

export interface OrdersBuckets {
  incoming: OrderRow[];
  orders: OrderRow[]; // all open on shift
  team_orders: OrderRow[];
  client_holds?: OrderRow[];
  client_hold_count?: number;
  withdrawals_incoming?: Record<string, unknown>[];
  withdrawals?: Record<string, unknown>[];
  team_withdrawals?: Record<string, unknown>[];
  [k: string]: unknown;
}

export interface RateInfo {
  crypto: string;
  market_rate: number;
  buy_rate: number;
  sell_rate: number;
  buy_commission_pct?: number;
  sell_commission_pct?: number;
  buy_markup?: number;
  sell_discount?: number;
  sell_pricing_mode?: "discount" | "markup" | string;
  sell_market_rate?: number;
  source?: string;
  frozen?: boolean;
  [k: string]: unknown;
}

// --- dashboard / shift ---
export const getMe = () => op<OperatorMe>("/me");
export const getOperatorHotWallet = () => op<HotWalletView>("/hot-wallet");

export interface HotWalletSwapCheck {
  key: string;
  ok: boolean;
  detail?: string;
}
export interface HotWalletSwapPreview {
  ok: boolean;
  preview_token?: string | null;
  expires_in?: number;
  coin?: string;
  address?: string;
  crypto_amount?: number;
  amount_rub?: number;
  market_rate?: number;
  fee_crypto?: string;
  fee_amount?: number;
  fee_rate_rub?: number;
  fee_amount_rub?: number;
  checks?: HotWalletSwapCheck[];
  [k: string]: unknown;
}
export interface HotWalletSwapSend {
  txid: string;
  request_id?: string;
  coin?: string;
  crypto_amount?: number;
  amount_rub?: number;
  fee_crypto?: string;
  fee_amount?: number;
  fee_amount_rub?: number;
  address?: string;
  already_sent?: boolean;
}
export interface HotWalletSwapBody {
  coin: "btc" | "ltc";
  address: string;
  crypto_amount: string;
  fee_crypto: "usdt" | "btc" | "ltc" | "trx" | "rub";
  fee_amount: string;
}

export const previewHotWalletSwap = (body: HotWalletSwapBody) =>
  op<HotWalletSwapPreview>("/hot-wallet/send/preview", { method: "POST", body });
export const confirmHotWalletSwap = (body: HotWalletSwapBody & { preview_token: string; totp_code: string }) =>
  op<HotWalletSwapSend>("/hot-wallet/send", { method: "POST", body });
export const getTeam = () => op<{ operators: TeamMember[]; [k: string]: unknown }>("/team");
export const getShifts = () => op<{ shifts: ShiftRow[]; [k: string]: unknown }>("/shifts");
export const startShift = (balances: ShiftBalance[]) => op<unknown>("/shift/start", { method: "POST", body: { balances } });
export const endShift = (note: string, balances: ShiftBalance[]) => op<unknown>("/shift/end", { method: "POST", body: { note, balances } });

// --- queue / orders ---
export const getQueue = () => op<QueueSummary>("/queue");
export const getOrders = (limit = 50, offset = 0) => op<OrdersBuckets>("/orders", { query: { limit, offset } });
export const lookupOrder = (order_id: string) => op<{ order: OrderRow; [k: string]: unknown }>("/orders/lookup", { query: { order_id } });
export const claimOrder = (id: string) => op<unknown>(`/orders/${id}/claim`, { method: "POST" });
export const transferOrderToFinance = (id: string) => op<unknown>(`/orders/${id}/transfer-to-finance`, { method: "POST" });
export const payoutOrder = (id: string, tx_hash: string, force = false) => op<unknown>(`/orders/${id}/payout`, { method: "POST", body: { tx_hash, force } });
export const markOrderPaid = (id: string, tx_hash: string) => op<unknown>(`/orders/${id}/paid`, { method: "PATCH", body: { tx_hash } });
export const confirmSellCryptoReceived = (id: string) =>
  op<{ order: OrderRow; already_confirmed?: boolean }>(`/orders/${id}/crypto_received`, { method: "POST" });
export const confirmPayinFiatReceived = (id: string) =>
  op<{ order: OrderRow }>(`/orders/${id}/payin_received`, { method: "POST" });
export const rejectPayinReceipt = (id: string) =>
  op<{ order: OrderRow }>(`/orders/${id}/payin_reject`, { method: "POST" });
export const sellPaid = (id: string, crypto_received: number, fiat_paid_out: number) =>
  op<unknown>(`/orders/${id}/sell_paid`, { method: "POST", body: { crypto_received, fiat_paid_out } });
export const getDolivCardBalances = () => op<{ total_float_rub?: string; traders_with_float?: number; [k: string]: unknown }>("/doliv/card-balances");
export const pushDolivPayout = (id: string, body: { pay_method?: string; phone?: string; card_number?: string } = {}) =>
  op<{ order_id: string; doliv_job?: unknown }>(`/orders/${id}/push-doliv-payout`, { method: "POST", body });
export const CLOSE_CLIENT_HOLD_REASON = "Снята блокировка обмена";
export const cancelOrder = (id: string, reason: string) => op<unknown>(`/orders/${id}/cancel`, { method: "POST", body: { reason } });
export const closeClientHold = (id: string) => cancelOrder(id, CLOSE_CLIENT_HOLD_REASON);
export const orderReceiptUrl = (id: string) => `/api/operator/orders/${id}/receipt`;
export const requestOrderVideo = (id: string) =>
  op<{ order: OrderRow; result?: string }>(`/orders/${id}/video`, { method: "POST" });
export const sendOrderReceiptToPayfast = (id: string) =>
  op<{ order: OrderRow; result?: string }>(`/orders/${id}/send-receipt`, { method: "POST" });
export const sendOrderWalletConfirmEarly = (id: string) =>
  op<{ order: OrderRow; result?: { ok?: boolean; detail?: string; status?: string } }>(
    `/orders/${id}/send-wallet-confirm`,
    { method: "POST" },
  );
export const reviewAccount = (id: number | string, action: "approve" | "reject") =>
  op<{ ok: boolean; account_review_status?: string; result?: string }>(`/users/${id}/account-review`, {
    method: "POST",
    body: { action },
  });
export const adjustUserBalance = (id: number | string, amount_rub: number, reason: string) =>
  op<{ ok: boolean; available_rub?: number; balance_rub?: number }>(`/users/${id}/balance`, {
    method: "POST",
    body: { amount_rub, reason },
  });

export type ExternalDealRow = {
  id: number;
  status?: string;
  order_status?: string;
  exchanger_name?: string;
  client_pays_rub?: number;
  amount_rub?: number;
  crypto?: string;
  expires_at?: string | null;
  has_receipt?: boolean;
  fingerprint?: string | null;
  client_stat?: Record<string, unknown> | null;
  check?: Record<string, unknown> | null;
  bill?: Record<string, unknown>;
  merchant_order_id?: string;
  client_transaction_id?: string | null;
  required_receipt_type?: number;
  receipt_submitted_at?: string | null;
  created_at?: string;
  [k: string]: unknown;
};

export async function listExternalDeals(status = "open") {
  try {
    return await op<{ deals?: ExternalDealRow[] }>("/external/deals", { query: { status } });
  } catch (e) {
    const key = String(status || "open").toLowerCase();
    if (e instanceof PanelApiError && e.status === 404 && (key === "open" || key === "pending")) {
      return op<{ deals?: ExternalDealRow[] }>("/external/deals/pending");
    }
    throw e;
  }
}
export const getExternalDeal = (id: number) => op<ExternalDealRow>(`/external/deals/${id}`);
export const confirmExternalDeal = (id: number) =>
  op<ExternalDealRow>(`/external/deals/${id}/confirm`, { method: "POST" });
export const cancelExternalDeal = (id: number) =>
  op<ExternalDealRow>(`/external/deals/${id}/cancel`, { method: "POST" });
export const requestExternalDealVideo = (id: number) =>
  op<ExternalDealRow>(`/external/deals/${id}/video`, { method: "POST" });
export const extendExternalDeal = (id: number, minutes = 20) =>
  op<ExternalDealRow>(`/external/deals/${id}/extend`, { method: "POST", body: { minutes } });
export const externalDealReceiptUrl = (id: number) => `/api/operator/external/deals/${id}/receipt`;

export interface HistoryPartnerOption { id: number; label: string }
export interface OrderHistoryPage {
  orders: OrderRow[];
  total: number;
  limit: number;
  offset: number;
  counts?: Record<string, number>;
  partner_options?: HistoryPartnerOption[];
}
export const getOrderHistory = (q: Record<string, unknown> = {}) =>
  op<OrderHistoryPage>("/orders/history", { query: q });
export const getOrderHistoryItem = (id: string) => op<OrderRow>(`/orders/history/${encodeURIComponent(id)}`);
export async function fetchOperatorOrderReceiptBlob(orderId: string): Promise<{ url: string; type: string }> {
  const token = getPanelToken("operator");
  const res = await fetch(`/api/operator/orders/${encodeURIComponent(orderId)}/receipt`, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new PanelApiError(
      res.status === 404 ? "Чек по заявке не найден" : "Не удалось открыть чек",
      res.status,
      null,
    );
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type || "application/octet-stream" };
}

// --- withdrawals ---
export const claimWithdrawal = (id: string) => op<unknown>(`/withdrawals/${id}/claim`, { method: "POST" });
export const cancelWithdrawal = (id: string) => op<unknown>(`/withdrawals/${id}/cancel`, { method: "POST" });
export const transferWithdrawalToFinance = (id: string) => op<unknown>(`/withdrawals/${id}/transfer-to-finance`, { method: "POST" });
export const payoutWithdrawal = (id: string, tx_hash: string, force = false) => op<unknown>(`/withdrawals/${id}/payout`, { method: "POST", body: { tx_hash, force } });
export const paidWithdrawal = (id: string) => op<unknown>(`/withdrawals/${id}/paid`, { method: "POST" });

export interface CasinoPayoutPlayer {
  user_id?: number;
  display_name?: string;
  available_rub?: number;
  raffle_tickets?: number;
  wagering?: Record<string, unknown>;
  payout_rail?: Record<string, unknown>;
  recent_games?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export interface CasinoPayoutRow {
  id: number;
  amount_rub?: number;
  method?: string;
  requisites?: string;
  crypto?: string;
  network?: string;
  status?: string;
  source?: string;
  operator_id?: number | null;
  player?: CasinoPayoutPlayer | null;
  player_username?: string | null;
  player_first_name?: string | null;
  [k: string]: unknown;
}

export interface CasinoPayoutsBuckets {
  incoming: CasinoPayoutRow[];
  mine: CasinoPayoutRow[];
  team: CasinoPayoutRow[];
  incoming_count?: number;
}

export const getCasinoPayouts = () => op<CasinoPayoutsBuckets>("/casino/payouts");
export const claimCasinoPayout = (id: string | number) =>
  op<unknown>(`/casino/payouts/${id}/claim`, { method: "POST" });
export const payoutCasinoWithdrawal = (id: string | number, tx_hash: string) =>
  op<unknown>(`/casino/payouts/${id}/payout`, { method: "POST", body: { tx_hash } });
export const paidCasinoWithdrawal = (id: string | number) =>
  op<unknown>(`/casino/payouts/${id}/paid`, { method: "POST" });
export const rejectCasinoPayout = (id: string | number) =>
  op<unknown>(`/casino/payouts/${id}/reject`, { method: "POST" });

// --- clients ---
export const searchUsers = (q: string, limit = 20) => op<{ users: Record<string, unknown>[]; [k: string]: unknown }>("/users/search", { query: { q, limit } });
export const getUser = (id: number | string) => op<Record<string, unknown>>(`/users/${id}`);
export const getUserCasinoProfile = (id: number | string) => op<CasinoClientProfile>(`/users/${id}/casino`);
export const getUserCasinoHistory = (id: number | string, query: { before?: string; game_type?: string } = {}) =>
  op<CasinoClientHistoryPage>(`/users/${id}/casino/history`, { query });
export const getUserDiscounts = (id: number | string, fiat_amount?: number) => op<Record<string, unknown>>(`/users/${id}/discounts`, { query: { fiat_amount } });
export const banUser = (id: number | string, reason: string, ban_type: "hard" | "soft") => op<unknown>(`/users/${id}/ban`, { method: "POST", body: { reason, ban_type } });
export const unbanUser = (id: number | string) => op<unknown>(`/users/${id}/unban`, { method: "POST" });

// --- create order ---
export interface CreateOrderInput {
  order_type: "buy" | "sell" | "sell_qr";
  buyer_user_id: number;
  fiat_amount?: number;
  crypto_amount?: number;
  crypto: string;
  wallet_address?: string;
  tx_hash?: string;
  network?: string;
  requisites?: string;
  client_name?: string;
  crypto_received?: number;
  fiat_paid_out?: number;
  note?: string;
  exchange_discount_id?: number;
  apply_balance?: boolean;
  manual_spread_pct?: number;
  received_fiat_amount?: number;
  requisite_ticket?: string;
  wallet_send?: WalletSendInput;
}
export const createOrder = (body: CreateOrderInput) => op<{ order: OrderRow; handoff_required?: boolean }>("/orders", { method: "POST", body });
export const getRate = (crypto = "usdt") => op<RateInfo>("/rate", { query: { crypto } });

export interface CoingeckoRateInfo {
  crypto: string;
  rub_rate: number;
  source?: string;
  [k: string]: unknown;
}
export const getCoingeckoRate = (crypto = "usdt") =>
  op<CoingeckoRateInfo>("/rate/coingecko", { query: { crypto } });

// --- payroll ---
export const getPayrollBalance = () => op<Record<string, unknown>>("/payroll/balance");
export const requestPayroll = (amount_rub: number, requisites: string) => op<unknown>("/payroll/request", { method: "POST", body: { amount_rub, requisites } });

// --- payout requisites (чужая карта/СБП под выплату + автоподбор чеков) ---
export interface PayoutPlanOrder {
  order_id: string;
  amount_rub?: number;
  user_id?: number | null;
  crypto?: string | null;
  [k: string]: unknown;
}
export interface PayoutPlanSplit {
  checks?: number[];
  sum_rub?: number;
  checks_count?: number;
  fill_minutes?: number;
  fill_eta_label?: string | null;
  [k: string]: unknown;
}
export interface PayoutPlan {
  orders?: PayoutPlanOrder[];
  orders_count?: number;
  orders_sum_rub?: number;
  checks_count?: number;
  doliv_rub?: number;
  leftover_rub?: number;
  closes?: boolean;
  free_rub?: number;
  computed_at?: string | null;
  is_applied?: boolean;
  kind?: string;
  hint?: string | null;
  now_hint?: string | null;
  close_when?: string | null;
  splits?: PayoutPlanSplit[];
  typical_rub?: number[];
  hour_msk?: number;
  weekday_label?: string | null;
  weeks_looked?: number;
  source?: string;
  solo_window?: boolean;
  [k: string]: unknown;
}
export interface PayinDiagnostics {
  unavailable?: boolean;
  computed_at?: string;
  readiness?: { ready: boolean; reasons: string[]; free_rub: number; reserved_rub: number };
  issuance?: {
    assigned_count: number; paid_count: number; canceled_count: number;
    first_assigned_at: string | null; last_assigned_at: string | null;
    last_order_id: string | null; health: "working" | "no_data" | "error";
  };
  traffic?: {
    sample_days: number; comparison_windows: number; sample_orders: number;
    matching_created: number; matching_paid: number; resolved_orders: number;
    probability_15m: number | null; probability_30m: number | null; probability_60m: number | null;
    payment_conversion: number | null; confidence: string; source: string;
    typical_rub: number[]; payment_sequences: number[][]; limitations: string;
  };
}
export interface PayoutAllocation {
  id: number;
  requisite_id: number;
  order_id: string | null;
  kind: "order" | "doliv" | "payin" | string;
  amount_rub: number;
  status: "RESERVED" | "PAID" | "CANCELED" | string;
  has_receipt?: boolean;
  has_buyer_receipt?: boolean;
  order_status?: string | null;
  order_crypto?: string | null;
  order_fiat_amount?: number | null;
  order_sub_token?: string | null;
  order_requisites?: string | null;
  user_id?: number | null;
  buyer_username?: string | null;
  buyer_first_name?: string | null;
  order_crypto_amount?: number | null;
  order_wallet?: string | null;
  receipt_ops_pending?: boolean;
  client_confirmed?: boolean;
  client_confirmed_at?: string | null;
  paid_at?: string | null;
  note?: string | null;
  created_at?: string;
  [k: string]: unknown;
}
export interface PayoutPoolOrder {
  order_id: string;
  fiat_amount: number;
  crypto?: string | null;
  sub_token?: string | null;
  requisites?: string | null;
  created_at?: string | null;
  [k: string]: unknown;
}
export interface PayoutRequisite {
  diagnostics?: PayinDiagnostics;
  id: number;
  operator_id: number;
  operator_display_name?: string | null;
  label?: string | null;
  method: "card" | "sbp" | string;
  requisites?: string | null;
  requisites_masked?: string | null;
  bank?: string | null;
  holder_name?: string | null;
  amount_rub: number;
  paid_rub: number;
  remaining_rub: number;
  reserved_rub?: number;
  free_rub?: number;
  cost_pct: number;
  cost_rub: number;
  crypto?: string;
  payoff_rub?: number;
  direction?: "payout" | "payin" | string;
  max_checks: number;
  used_checks?: number | null;
  checks_left?: number | null;
  has_open_reserve?: boolean | null;
  doliv_limit_rub: number;
  status: string;
  deadline_at?: string | null;
  closed_at?: string | null;
  close_note?: string | null;
  confirmed_at?: string | null;
  source_sell_order_id?: string | null;
  source_withdrawal_id?: number | null;
  created_at?: string;
  is_mine?: boolean;
  plan?: PayoutPlan | null;
  allocations?: PayoutAllocation[];
  [k: string]: unknown;
}
export interface PayoutRequisiteInput {
  method: "card" | "sbp";
  requisites: string;
  amount_rub: number;
  cost_pct: number;
  crypto?: PayoutCrypto;
  direction?: "payout" | "payin";
  label?: string;
  bank: string;
  holder_name: string;
  window_minutes?: number;
  max_checks?: number;
  doliv_limit_rub?: number;
}
export type PayoutCrypto = "usdt" | "btc" | "trx" | "ltc";
export interface PayoutPayoffQuote {
  amount_rub: number;
  cost_pct: number;
  cost_rub: number;
  payoff_rub: number;
  crypto: string;
  rate_rub: number;
  crypto_amount: number;
  rate_source?: string;
  direction?: string;
}
export const quotePayoutPayoff = (
  amount_rub: number,
  cost_pct: number,
  crypto: PayoutCrypto,
  direction: "payout" | "payin" = "payin",
) =>
  op<PayoutPayoffQuote>("/payout-requisites/quote", {
    query: { amount_rub, cost_pct, crypto, direction },
  });
export const listPayoutRequisites = (include_closed = false) =>
  op<{
    mine: PayoutRequisite[];
    team: PayoutRequisite[];
    pool_orders?: PayoutPoolOrder[];
    unopened_withdrawals?: { id: number; triangle_label: string }[];
  }>("/payout-requisites", {
    query: { include_closed },
  });
export const createPayoutRequisite = (body: PayoutRequisiteInput) =>
  op<{ requisite: PayoutRequisite }>("/payout-requisites", { method: "POST", body });
export const createPayoutRequisiteFromSell = (
  orderId: string,
  body?: { method?: "card" | "sbp"; requisites?: string; bank?: string; holder_name?: string },
) =>
  op<{ requisite: PayoutRequisite }>(`/payout-requisites/from-sell/${encodeURIComponent(orderId)}`, {
    method: "POST",
    body: body ?? {},
  });
export const getPayoutRequisite = (id: number) =>
  op<{ requisite: PayoutRequisite }>(`/payout-requisites/${id}`);
export const getPayoutRequisitePlan = (id: number, refresh = false) =>
  op<{ plan: PayoutPlan }>(`/payout-requisites/${id}/plan`, { query: { refresh } });
export const reservePayoutRequisite = (id: number, order_ids?: string[]) =>
  op<{ requisite: PayoutRequisite; allocations: PayoutAllocation[] }>(`/payout-requisites/${id}/reserve`, {
    method: "POST",
    body: { order_ids: order_ids ?? null },
  });
export function markPayoutAllocationPaid(id: number, allocationId: number, file: File, fiat_paid_out?: number) {
  const f = new FormData();
  f.append("file", file);
  if (fiat_paid_out != null) f.append("fiat_paid_out", String(fiat_paid_out));
  return op<{ requisite: PayoutRequisite; allocation: PayoutAllocation; order?: unknown }>(
    `/payout-requisites/${id}/allocations/${allocationId}/paid`,
    { method: "POST", body: f },
  );
}
export function attachPayoutAllocationReceipt(id: number, allocationId: number, file: File) {
  const f = new FormData();
  f.append("file", file);
  return op<{ allocation: PayoutAllocation }>(
    `/payout-requisites/${id}/allocations/${allocationId}/receipt`,
    { method: "POST", body: f },
  );
}
export const cancelPayoutAllocation = (id: number, allocationId: number) =>
  op<{ requisite: PayoutRequisite; allocation: PayoutAllocation }>(
    `/payout-requisites/${id}/allocations/${allocationId}/cancel`,
    { method: "POST" },
  );
export function addPayoutDoliv(id: number, amount_rub: number, note?: string, file?: File | null) {
  const f = new FormData();
  f.append("amount_rub", String(amount_rub));
  if (note) f.append("note", note);
  if (file) f.append("file", file);
  return op<{ requisite: PayoutRequisite; allocation: PayoutAllocation }>(`/payout-requisites/${id}/doliv`, {
    method: "POST",
    body: f,
  });
}
export const closePayoutRequisite = (id: number, note?: string) =>
  op<{ requisite: PayoutRequisite; released: number }>(`/payout-requisites/${id}/close`, {
    method: "POST",
    body: { note: note ?? null },
  });
export const cancelPayoutRequisite = (id: number, note?: string) =>
  op<{ requisite: PayoutRequisite; released: number }>(`/payout-requisites/${id}/cancel`, {
    method: "POST",
    body: { note: note ?? null },
  });
export const confirmPayoutRequisite = (id: number) =>
  op<{ requisite: PayoutRequisite; already_confirmed?: boolean }>(`/payout-requisites/${id}/confirm`, {
    method: "POST",
  });
export const updatePayoutRequisiteMaxChecks = (id: number, max_checks: number) =>
  op<{ requisite: PayoutRequisite }>(`/payout-requisites/${id}/max-checks`, {
    method: "POST",
    body: { max_checks },
  });

// --- reviews ---
export const getReviews = (status = "pending", page = 1, limit = 20) =>
  op<{ reviews: Record<string, unknown>[]; [k: string]: unknown }>("/reviews", { query: { status, page, limit } });
export const getReviewsPendingCount = () => op<{ count: number }>("/reviews/pending-count");
export const publishReview = (id: number | string, bonus: "text" | "photo" | "none") => op<unknown>(`/reviews/${id}/publish`, { method: "POST", body: { bonus } });
export const rejectReview = (id: number | string, reason?: string) => op<unknown>(`/reviews/${id}/reject`, { method: "POST", body: { reason } });

// --- avatar / profile ---
export function uploadAvatar(file: File) {
  const f = new FormData();
  f.append("file", file);
  return op<unknown>("/avatar", { method: "POST", body: f });
}
export const deleteAvatar = () => op<unknown>("/avatar", { method: "DELETE" });

// --- Ops AI ---
export interface AiSession {
  id: number;
  title?: string;
  updated_at?: string;
  [k: string]: unknown;
}
export interface AiMessage {
  id: number;
  role: string;
  content: string;
  sources_json?: { path?: string; title?: string; score?: number }[];
  created_at?: string;
  [k: string]: unknown;
}
export interface AiDevTask {
  id: number;
  title: string;
  request_text: string;
  priority?: string;
  status: string;
  summary?: string;
  file_list?: string[];
  freeze_hit?: boolean;
  cursor_prompt?: string;
  smoke_plan?: string;
  risks?: string;
  reject_reason?: string;
  created_at?: string;
  updated_at?: string;
  [k: string]: unknown;
}
export const aiStatus = () => op<{ provider: string; configured: boolean; pending_review: number }>("/ai/status");
export const aiListSessions = () => op<{ sessions: AiSession[] }>("/ai/sessions");
export const aiCreateSession = (title = "Чат") => op<AiSession>("/ai/sessions", { method: "POST", body: { title } });
export const aiGetMessages = (sessionId: number) =>
  op<{ session: AiSession; messages: AiMessage[] }>(`/ai/sessions/${sessionId}/messages`);
export const aiSendMessage = (
  sessionId: number,
  content: string,
  ui_context?: {
    path?: string;
    search?: string;
    title?: string;
    hint?: string;
    order_id?: string;
    client_id?: number;
  },
  images?: File[],
) => {
  const hasImages = !!(images && images.length);
  if (hasImages) {
    const fd = new FormData();
    fd.append("content", content || "");
    if (ui_context) fd.append("ui_context", JSON.stringify(ui_context));
    for (const f of images!) fd.append("images", f);
    return op<{
      user: AiMessage;
      assistant: AiMessage;
      sources: unknown[];
      escalated_task?: { id: number; title?: string; status?: string };
    }>(`/ai/sessions/${sessionId}/messages`, { method: "POST", body: fd });
  }
  return op<{
    user: AiMessage;
    assistant: AiMessage;
    sources: unknown[];
    escalated_task?: { id: number; title?: string; status?: string };
  }>(`/ai/sessions/${sessionId}/messages`, {
    method: "POST",
    body: { content, ...(ui_context ? { ui_context } : {}) },
  });
};
export const aiMarkUseful = (sessionId: number, messageId: number, note?: string) =>
  op<unknown>(`/ai/sessions/${sessionId}/messages/${messageId}/useful`, { method: "POST", body: { note } });
export const aiListMyTasks = (status = "all", page = 1) =>
  op<{ tasks: AiDevTask[]; total: number }>("/ai/tasks", { query: { status, page } });
export const aiGetMyTask = (id: number) => op<AiDevTask>(`/ai/tasks/${id}`);
export const aiCreateTask = (body: {
  request_text: string;
  priority?: string;
  title?: string;
  source_session_id?: number;
  source_message_id?: number;
  ui_context?: {
    path?: string;
    search?: string;
    title?: string;
    hint?: string;
    order_id?: string;
    client_id?: number;
  };
}) => op<AiDevTask>("/ai/tasks", { method: "POST", body });

export type AiTelegramStatus = {
  operator_id: number;
  username?: string;
  display_name?: string | null;
  telegram_user_id?: number | null;
  telegram_linked: boolean;
  digest_enabled: boolean;
  digest_hour: number;
  digest_tz?: string;
};

export const aiTelegramStatus = () => op<AiTelegramStatus>("/ai/telegram");
export const aiTelegramBindLink = () =>
  op<{ token: string; deep_link: string; expires_at: string; command: string }>("/ai/telegram/bind-link", {
    method: "POST",
  });
export const aiTelegramUnbind = () => op<AiTelegramStatus>("/ai/telegram", { method: "DELETE" });
export const aiTelegramDigest = (body: { enabled?: boolean; hour?: number }) =>
  op<AiTelegramStatus>("/ai/telegram/digest", { method: "PATCH", body });
export const aiListMemories = (opts?: { mine?: boolean; kind?: string; limit?: number }) =>
  op<{ memories: { id: number; title: string; body: string; kind: string; occurred_at?: string }[] }>(
    "/ai/memories",
    { query: { mine: opts?.mine ?? true, kind: opts?.kind, limit: opts?.limit ?? 40 } },
  );
export const aiCreateMemory = (body: {
  title: string;
  body: string;
  kind?: string;
  importance?: number;
}) => op<unknown>("/ai/memories", { method: "POST", body });

export type AiPrivacy = {
  consent_required_version: string;
  has_valid_consent: boolean;
  consent?: Record<string, unknown> | null;
  allow_images?: boolean;
  audit_ttl_days?: number;
};
export const aiPrivacy = () => op<AiPrivacy>("/ai/privacy");
export const aiGrantConsent = (scopes: string[] = ["llm"], source = "ops_ui") =>
  op<Record<string, unknown>>("/ai/consent", { method: "POST", body: { scopes, source } });

export interface DeployEvent {
  id: number;
  idempotency_key?: string;
  environment?: string;
  status: string;
  title?: string;
  sectors?: string[];
  technical_summary?: string;
  user_impact?: string;
  plain_explanation?: string;
  commit_sha?: string | null;
  build_id?: string | null;
  actor?: string | null;
  logs_url?: string | null;
  created_at?: string;
  confirmed_at?: string | null;
  notify_sent_at?: string | null;
  [k: string]: unknown;
}
export interface ChangelogDay {
  date: string;
  count: number;
}
export const getChangelog = (opts?: { day?: string; limit?: number; offset?: number }) =>
  op<{
    total: number;
    days: ChangelogDay[];
    items: DeployEvent[];
    items_by_day: Record<string, DeployEvent[]>;
  }>("/changelog", { query: { day: opts?.day, limit: opts?.limit ?? 50, offset: opts?.offset ?? 0 } });
export const getDeployEvent = (id: number) => op<DeployEvent>(`/deploy/${id}`);
export const confirmDeployEvent = (id: number, note?: string) =>
  op<DeployEvent>(`/deploy/${id}/confirm`, { method: "POST", body: { note } });

export interface AntispamPhrase {
  id: number;
  phrase: string;
  normalized?: string;
  created_by_operator_id?: number | null;
  created_at?: string | null;
  [k: string]: unknown;
}
export const listAntispamPhrases = () =>
  op<{ items: AntispamPhrase[]; builtin: string[] }>("/antispam/phrases");
export const createAntispamPhrase = (phrase: string) =>
  op<AntispamPhrase>("/antispam/phrases", { method: "POST", body: { phrase } });
export const deleteAntispamPhrase = (id: number) =>
  op<{ ok: boolean; id: number }>(`/antispam/phrases/${id}`, { method: "DELETE" });

// --- project wallet payout (manual buy) ---
export interface WalletSendInput {
  preview_token: string;
  totp_code: string;
  allow_other_client?: boolean;
}
export interface WalletPayoutMode {
  mode: "operator" | "project";
  coins: string[];
  can_send: boolean;
  preview_ttl_sec: number;
}
export interface WalletPreviewCheck {
  key: string;
  ok: boolean;
  detail?: string;
}
export interface WalletPreview {
  ok: boolean;
  preview_token: string | null;
  expires_in: number;
  coin: string;
  address: string;
  crypto_amount: number;
  amount_rub: number;
  market_rate: number;
  rate_used?: number;
  checks: WalletPreviewCheck[];
  sent_before: number;
  operator_left_rub: number;
  wallet_day_left_rub: number;
  per_payout_max_rub: number;
  fee_crypto: number;
  fee_rub: number;
  fee_sat_vb?: number | null;
  fee_estimated?: boolean;
  balance_crypto: number;
  balance_after_crypto: number;
  pending_crypto?: number;
  pending_covers?: boolean;
  dry_run?: boolean;
  order_id?: string;
  cashback_applied?: number;
  exchange_discount_applied?: number;
  client?: { user_id?: number | null; username?: string | null; first_name?: string | null };
  [k: string]: unknown;
}
export const getPayoutWalletMode = () => op<WalletPayoutMode>("/payout-wallet-mode");
export const previewNewOrderWalletSend = (body: CreateOrderInput) =>
  op<WalletPreview>("/orders/wallet-preview", { method: "POST", body });
export const previewOrderWalletSend = (id: string) =>
  op<WalletPreview>(`/orders/${id}/wallet-preview`, { method: "POST" });
export const sendOrderFromProjectWallet = (id: string, body: WalletSendInput) =>
  op<{ order: OrderRow; txid: string; paid_from: string }>(`/orders/${id}/wallet-send`, { method: "POST", body });
