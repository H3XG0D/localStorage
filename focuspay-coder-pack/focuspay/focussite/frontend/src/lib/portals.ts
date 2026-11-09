// Partner and freelance-exchanger portals. Separate account kinds with their own
// bearer tokens (scope "partner" / "exchanger"), distinct from the buyer session.
import { api } from "@/lib/api";

// ---------------- Partner ----------------
export interface PartnerLoginResult {
  account_kind?: "partner";
  requires_2fa?: boolean;
  pre_auth_token?: string;
  access_token?: string;
  token_type?: string;
  partner: Record<string, unknown>;
}

export function partnerLogin(username: string, password: string) {
  return api<PartnerLoginResult>("/auth/partner/login", { method: "POST", scope: null, body: { username, password } });
}
export function partnerLogin2FA(pre_auth_token: string, code: string) {
  return api<PartnerLoginResult>("/auth/partner/login/2fa", { method: "POST", scope: null, body: { pre_auth_token, code } });
}
export const partnerMe = () => api<{ partner: Record<string, unknown> }>("/auth/partner/me", { scope: "partner" });

export interface PartnerDashboard {
  campaign: { id: number; code: string; name?: string; bonus_percent: number; partner_commission_percent: number; ad_spend_rub: number };
  tier: Record<string, number | boolean | null>;
  commission_basis_label: string;
  balance_rub: number;
  available_rub: number;
  pending_withdraw_rub: number;
  attracted_users: number;
  paid_orders_count: number;
  paid_fiat_sum: number;
  period_accrued: number;
  period_paid_out: number;
  ref_token: string;
  referral_link: string;
  referral_web_link: string;
  referral_onion_link?: string | null;
}
export const partnerDashboard = () => api<PartnerDashboard>("/partner/dashboard", { scope: "partner" });

export interface PartnerLedgerEntry {
  id: number;
  type: string;
  amount_rub: number;
  order_id?: string | null;
  note?: string | null;
  created_at?: string | null;
}
export interface PartnerLedger {
  entries: PartnerLedgerEntry[];
  total: number;
  balance_rub: number;
  available_rub: number;
  pending_withdraw_rub: number;
  has_pending_withdrawal: boolean;
  min_withdraw_card_rub: number;
  unified_balance?: boolean;
}
export const partnerLedger = (limit = 30) =>
  api<PartnerLedger>("/partner/ledger", { scope: "partner", query: { limit } });

export interface PartnerUserRow {
  user_id: number;
  username?: string | null;
  first_name?: string | null;
  assigned_at?: string | null;
  total_orders: number;
  paid_orders: number;
}
export const partnerUsers = (limit = 20) =>
  api<{ users: PartnerUserRow[]; total: number }>("/partner/users", { scope: "partner", query: { limit } });

export interface PartnerOrderRow {
  order_id: string;
  status: string;
  direction: string;
  crypto: string;
  fiat_amount: number;
  crypto_amount?: number | null;
  created_at?: string | null;
}
export const partnerOrders = (limit = 20) =>
  api<{ orders: PartnerOrderRow[]; total: number }>("/partner/orders", { scope: "partner", query: { limit } });

export interface PartnerWithdrawal {
  id: number;
  amount_rub: number;
  method: "card" | "crypto";
  requisites: string;
  crypto?: string | null;
  network?: string | null;
  status: string;
  phase?: string | null;
  status_label?: string | null;
  status_hint?: string | null;
  network_fee_rub?: number | null;
  payout_amount_rub?: number | null;
  payout_tx_hash?: string | null;
  reject_reason?: string | null;
  created_at?: string | null;
  processed_at?: string | null;
}
export interface PartnerWithdrawals {
  withdrawals: PartnerWithdrawal[];
  unified_balance?: boolean;
}
export const partnerWithdrawals = () => api<PartnerWithdrawals>("/partner/withdrawals", { scope: "partner" });
export function partnerWithdraw(body: { amount_rub: number; method: string; requisites: string; crypto?: string | null; network?: string | null }) {
  return api<PartnerWithdrawal>("/partner/withdrawals", { method: "POST", scope: "partner", body });
}

// ---------------- Exchanger ----------------
export interface ExchangerLoginResult {
  access_token?: string;
  token_type?: string;
  requires_2fa?: boolean;
  pre_auth_token?: string;
  exchanger: Record<string, unknown>;
}
export function exchangerLogin(username: string, password: string) {
  return api<ExchangerLoginResult>("/auth/exchanger/login", { method: "POST", scope: null, body: { username, password } });
}
export function exchangerLogin2FA(pre_auth_token: string, code: string) {
  return api<ExchangerLoginResult>("/auth/exchanger/login/2fa", { method: "POST", scope: null, body: { pre_auth_token, code } });
}
export const exchangerMe = () => api<{ exchanger: Record<string, unknown> }>("/auth/exchanger/me", { scope: "exchanger" });

export interface ExchangerDashboard {
  exchanger_id: number;
  name?: string;
  username?: string;
  role?: string;
  is_owner?: boolean;
  totp_enabled?: boolean;
  balance_usd: number;
  available_usd: number;
  has_pending_payout: boolean;
  pending_payout_gross_usd: number;
  deal_count: number;
  payout_count: number;
  turnover_base_rub: number;
  turnover_client_rub: number;
  total_credited_usd: number;
  total_paid_out_usd: number;
  conversion_pct?: number | null;
  payout_threshold_usd: number;
  withdraw_fee_usd: number;
  withdraw_fees?: Record<string, number>;
  active_deal_ids: number[];
  active_count: number;
  markup_pct?: number | null;
  markup_mode?: string | null;
  markup_hint?: string | null;
  [key: string]: unknown;
}
export const exchangerDashboard = () => api<ExchangerDashboard>("/exchanger/dashboard", { scope: "exchanger" });

export type ExchangerRatesSnapshot = {
  rates: Partial<Record<string, { market: number; currency?: string }>>;
  updated_at?: number | null;
  source?: string;
  frozen?: boolean;
};

export const exchangerRates = () => api<ExchangerRatesSnapshot>("/exchanger/rates", { scope: "exchanger" });

export type ExchangerRekiBand = { min_rub: number; max_rub: number; available_rub: number };

export type ExchangerRekiSection = {
  sub_token: string;
  title?: string;
  count: number;
  total_rub: number;
  bands: ExchangerRekiBand[];
};

export type ExchangerRekiSnapshot = {
  sections: ExchangerRekiSection[];
  snapshot_at?: string | null;
  stale?: boolean;
  ttl_seconds?: number;
};

export const exchangerReki = () => api<ExchangerRekiSnapshot>("/exchanger/reki", { scope: "exchanger" });

export type PortalRecord = Record<string, unknown>;
export type PortalQuery = Record<string, string | number | boolean | null | undefined>;

export interface ExchangerDealsResponse {
  items: PortalRecord[];
  total: number;
  active_count: number;
}

export const exchangerDeals = (query: PortalQuery = {}) => api<ExchangerDealsResponse>("/exchanger/deals", { scope: "exchanger", query });
export const exchangerDealPreview = (
  amountRubOrOpts: number | { amount_rub?: number; amount_crypto?: number; crypto?: string },
) => {
  const opts = typeof amountRubOrOpts === "number" ? { amount_rub: amountRubOrOpts } : amountRubOrOpts;
  const query: Record<string, string | number> = {};
  if (opts.amount_crypto != null && opts.amount_crypto > 0) {
    query.amount_crypto = opts.amount_crypto;
    if (opts.crypto) query.crypto = opts.crypto;
  } else if (opts.amount_rub != null) {
    query.amount_rub = opts.amount_rub;
  }
  return api<PortalRecord>("/exchanger/deals/preview", { scope: "exchanger", query });
};
export const exchangerCreateDeal = (body: {
  amount_rub?: number;
  amount_crypto?: number;
  crypto: string;
  sub_token: string;
  note?: string;
  client_is_new: boolean;
  payout_on_credit?: boolean;
  payout_wallet?: string;
}) => api<PortalRecord>("/exchanger/deals", { method: "POST", scope: "exchanger", body });
export const exchangerActiveDeals = () => api<{ active: boolean; deals: PortalRecord[]; deal?: PortalRecord }>("/exchanger/deals/active", { scope: "exchanger" });
export const exchangerDeal = (id: number) => api<PortalRecord>(`/exchanger/deals/${id}`, { scope: "exchanger" });
export const exchangerConfirmPaid = (id: number) => api<PortalRecord>(`/exchanger/deals/${id}/confirm-paid`, { method: "POST", scope: "exchanger" });
export const exchangerCancelDeal = (id: number) => api<PortalRecord>(`/exchanger/deals/${id}/cancel`, { method: "POST", scope: "exchanger" });
export function exchangerUploadReceipt(id: number, file: File) {
  const body = new FormData();
  body.append("file", file);
  return api<PortalRecord>(`/exchanger/deals/${id}/receipt`, { method: "POST", scope: "exchanger", body });
}

export const exchangerPayoutBalance = () => api<PortalRecord>("/exchanger/payouts/balance", { scope: "exchanger" });
export const exchangerPayoutPreview = (grossUsd: number, crypto: string) => api<PortalRecord>("/exchanger/payouts/preview", { scope: "exchanger", query: { gross_usd: grossUsd, crypto } });
export interface ExchangerPayoutsResponse { items: PortalRecord[]; total: number }
export const exchangerPayouts = (query: PortalQuery = {}) => api<ExchangerPayoutsResponse>("/exchanger/payouts", { scope: "exchanger", query });
export const exchangerCreatePayout = (body: { gross_usd: number; crypto: string; wallet: string }) => api<PortalRecord>("/exchanger/payouts", { method: "POST", scope: "exchanger", body });
export const exchangerRubCardPayout = (body: { amount_rub: number; pay_method: "sbp" | "c2c"; phone?: string; card_number?: string; recipient_name?: string; bank?: string }) =>
  api<PortalRecord>("/exchanger/payouts/rub-card", { method: "POST", scope: "exchanger", body });

export interface ExchangerHistoryResponse { items: PortalRecord[]; total: number }
export const exchangerHistory = (query: PortalQuery = {}) => api<ExchangerHistoryResponse>("/exchanger/history", { scope: "exchanger", query });

export interface ExchangerChatResponse { thread: PortalRecord; messages: PortalRecord[]; has_more_older?: boolean; oldest_id?: number | null }
export const exchangerChat = (query: PortalQuery = {}) => api<ExchangerChatResponse>("/exchanger/chat", { scope: "exchanger", query });
export const exchangerSendChat = (body: string) => api<{ message: PortalRecord }>("/exchanger/chat", { method: "POST", scope: "exchanger", body: { body } });
export function exchangerSendChatImage(file: File, caption?: string) {
  const body = new FormData();
  body.append("file", file);
  if (caption) body.append("caption", caption);
  return api<{ message: PortalRecord }>("/exchanger/chat/messages/image", { method: "POST", scope: "exchanger", body });
}
export function exchangerSendChatFile(file: File, caption?: string) {
  const body = new FormData();
  body.append("file", file);
  if (caption) body.append("caption", caption);
  return api<{ message: PortalRecord }>("/exchanger/chat/messages/file", { method: "POST", scope: "exchanger", body });
}

export const exchangerChangePassword = (currentPassword: string, newPassword: string) => api<{ ok: boolean }>("/auth/exchanger/change-password", { method: "POST", scope: "exchanger", body: { current_password: currentPassword, new_password: newPassword } });

// 2FA кабинета магазина: setup → показать секрет, confirm → включить, disable → выключить.
export const exchangerTotpSetup = () => api<{ secret: string; uri: string; enabled: boolean }>("/auth/exchanger/totp/setup", { method: "POST", scope: "exchanger" });
export const exchangerTotpConfirm = (code: string) => api<{ ok: boolean; enabled: boolean }>("/auth/exchanger/totp/confirm", { method: "POST", scope: "exchanger", body: { code } });
export const exchangerTotpDisable = (currentPassword: string, code: string) =>
  api<{ ok: boolean; enabled: boolean }>("/auth/exchanger/totp/disable", { method: "POST", scope: "exchanger", body: { current_password: currentPassword, code } });

// Логины магазина: владелец выпускает сотрудников (только реквизиты и чеки, без выводов).
export interface ExchangerAccount {
  id: number;
  username: string;
  role: string;
  is_owner: boolean;
  label?: string | null;
  is_active: boolean;
  totp_enabled: boolean;
  created_at?: string | null;
}
export interface ExchangerCredentials {
  username: string;
  password: string;
  role?: string;
  login_path?: string;
  login_url?: string;
}
export const exchangerAccounts = () => api<{ items: ExchangerAccount[]; current_account_id: number }>("/exchanger/accounts", { scope: "exchanger" });
export const exchangerCreateClerk = (body: { username: string; label?: string }) =>
  api<{ account: ExchangerAccount; credentials: ExchangerCredentials }>("/exchanger/accounts", { method: "POST", scope: "exchanger", body });
export const exchangerResetAccountPassword = (id: number) => api<ExchangerCredentials>(`/exchanger/accounts/${id}/reset-password`, { method: "POST", scope: "exchanger" });
export const exchangerUpdateAccount = (id: number, body: { is_active?: boolean; label?: string }) =>
  api<{ account: ExchangerAccount }>(`/exchanger/accounts/${id}`, { method: "PATCH", scope: "exchanger", body });

export interface ExchangerApiKey {
  id: number;
  api_key: string;
  secret_hint: string;
  is_active: boolean;
  created_at?: string | null;
  revoked_at?: string | null;
  secret?: string;
}
export const exchangerApiKey = () => api<{ key: ExchangerApiKey | null }>("/exchanger/api-keys", { scope: "exchanger" });
