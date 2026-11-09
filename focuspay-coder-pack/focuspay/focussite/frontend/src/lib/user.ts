// Authenticated user cabinet: profile, order history, unified balance,
// referral, promo redemption, discounts, and the FocusLucky battle game.
import { api } from "@/lib/api";
import type { User } from "@/lib/auth";
import type { Order } from "@/lib/orders";

export interface Profile {
  user: User;
  stats: { total_orders: number; completed_orders: number };
}

export interface HistoryOrder extends Order {
  id: number;
  updated_at?: string | null;
  promo_code?: string | null;
  promo_bonus_percent?: number | null;
  cashback_applied_rub?: number;
  cashback_accrued_rub?: number;
}

export interface OrdersPage {
  orders: HistoryOrder[];
  total?: number;
  limit: number;
  offset: number;
}

/** Unified balance + referral snapshot (fields per user_unified_balance.py). */
export interface BalanceStats {
  balance_rub: number;
  available_rub: number;
  cashback_rub: number;
  promo_rub: number;
  referral_rub: number;
  total_accrued_rub: number;
  saved_rub: number;
  use_on_next: boolean;
  has_pending_withdrawal: boolean;
  min_withdraw_card_rub: number;
  ref_token: string;
  telegram_link: string;
  web_invite_link: string;
  referred_count: number;
  paid_orders_count: number;
  referral_total_accrual_rub: number;
  casino_total_rub?: number;
  casino_l1_rub?: number;
  casino_l2_rub?: number;
  payout_rail?: {
    fiat_deposited_rub?: number;
    card_withdrawn_rub?: number;
    remaining_rub?: number;
    crypto_allowed?: boolean;
  };
  [key: string]: unknown;
}

export interface LedgerEntry {
  id?: number;
  type?: string;
  amount_rub?: number;
  created_at?: string;
  note?: string;
  [key: string]: unknown;
}

export type WithdrawMethod = "card" | "crypto";
export interface WithdrawInput {
  amount_rub: number;
  method: WithdrawMethod;
  requisites: string;
  crypto?: string | null;
  network?: string | null;
  source?: "balance" | "casino";
}

export interface WithdrawalRow {
  id: number;
  amount_rub?: number;
  method?: string;
  status?: string;
  source?: string;
  crypto?: string | null;
  network?: string | null;
  requisites?: string | null;
  created_at?: string;
  processed_at?: string | null;
  phase?: "awaiting" | "processing" | "paid" | "rejected" | "canceled";
  cancellable?: boolean;
  status_label?: string;
  status_hint?: string;
  [key: string]: unknown;
}

// --- profile / orders ---
export const getProfile = () => api<Profile>("/user/profile");
export const getMyOrders = (limit = 20, offset = 0) =>
  api<OrdersPage>("/user/orders", { query: { limit, offset } });
export const getMyOrder = (orderId: string) => api<HistoryOrder>(`/user/orders/${orderId}`);

// --- balance / cashback ---
export const getBalance = () => api<BalanceStats>("/user/balance");
export const getLedger = (limit = 30) =>
  api<{ entries?: LedgerEntry[]; items?: LedgerEntry[] } | LedgerEntry[]>("/user/balance/ledger", {
    query: { limit },
  });
export const getWithdrawals = (limit = 30, source?: "balance" | "casino") =>
  api<{ withdrawals?: WithdrawalRow[] }>("/user/balance/withdrawals", { query: { limit, source } });
export const cancelWithdrawal = (id: number) =>
  api<WithdrawalRow>(`/user/balance/withdrawals/${id}/cancel`, { method: "POST" });
export const setCashbackOnNext = (use_on_next: boolean) =>
  api<unknown>("/user/balance", { method: "PATCH", body: { use_on_next } });
export const getDiscounts = () => api<unknown>("/user/discounts");
export const withdraw = (input: WithdrawInput) =>
  api<{ id: number; status: string; amount_rub: number }>("/user/balance/withdraw", { method: "POST", body: input });

export type CasinoCryptoCoin = "btc" | "ltc";

export type CasinoCryptoAddress = {
  coin: CasinoCryptoCoin;
  address: string;
  network: string;
  min_rub: number;
  rate: number | null;
  hint: string;
};

export type CasinoCryptoDeposit = {
  coin: string;
  txid: string;
  address: string;
  amount_crypto: string;
  amount_rub: string | null;
  status: string;
  confirmations: number;
  created_at?: string | null;
};

export const issueCasinoCryptoAddress = (coin: CasinoCryptoCoin) =>
  api<CasinoCryptoAddress>("/user/casino/crypto-deposit/address", { method: "POST", body: { coin } });

export const getCasinoCryptoDeposits = () =>
  api<{ deposits?: CasinoCryptoDeposit[] }>("/user/casino/crypto-deposits");

// --- promo ---
export const redeemPromo = (code: string) =>
  api<{ balance?: BalanceStats; campaign_kind?: string; amount_rub?: number; min_order_rub?: number; [k: string]: unknown }>("/user/promo/redeem", { method: "POST", body: { code } });

export function promoRedeemedText(res: {
  campaign_kind?: unknown;
  kind?: unknown;
  title?: unknown;
  amount_rub?: unknown;
  min_order_rub?: unknown;
}) {
  if (String(res.kind || "") === "tournament") {
    const title = String(res.title || "").trim();
    return title || "Вы записаны на турнир";
  }
  if (String(res.campaign_kind || "") === "exchange_discount") {
    const amount = Number(res.amount_rub || 0);
    const min = Number(res.min_order_rub || 0);
    if (min > 0) return `Скидка ${amount} ₽ на обмен от ${min} ₽`;
    return "Скидка на обмен активирована";
  }
  return "Промокод активирован";
}

export interface ReviewOffer {
  eligible: boolean;
  pending: boolean;
  reason: "pending" | "no_buy" | "already_reviewed" | null;
  order_id: string | null;
  text_rub: number;
  min_len: number;
  needs_photo: boolean;
}

export const getReviewOffer = () => api<ReviewOffer>("/user/review");
export const submitReview = (text: string) =>
  api<{ ok: boolean; id: number; text_rub: number; order_id?: string | null }>("/user/review", {
    method: "POST",
    body: { text },
  });

// --- referral ---
export const getReferral = () => api<BalanceStats>("/user/referral");
export const getReferralLedger = () =>
  api<{ items?: LedgerEntry[] } | LedgerEntry[]>("/user/referral/ledger");
export const applyReferral = (ref_token: string) =>
  api<{ applied: boolean }>("/user/referral/apply", { method: "POST", body: { ref_token } });
export const finalizeReferral = () => api<{ ok: boolean }>("/user/referral/finalize", { method: "POST" });
export const referralWithdraw = (input: WithdrawInput) =>
  api<{ id: number; status: string; amount_rub: number }>("/user/referral/withdraw", { method: "POST", body: input });

// --- battle (FocusLucky) ---
export type BattleSide = "red" | "blue";
export interface BattleRound {
  round_id: number;
  seconds_left: number;
  red_total: number;
  blue_total: number;
  red_pct: number;
  blue_pct: number;
  bank: number;
  status: "open" | "locked" | "resolved" | "cancelled";
  my_bet: { side: BattleSide; amount: number } | null;
  balance_available: number;
}
export interface BattleHistoryItem {
  round_id: number;
  winner: BattleSide | null;
  red_total: number;
  blue_total: number;
  ended_at: string;
}
export const battleEnabled = () => api<{ enabled: boolean }>("/user/battle/enabled");
export const battleCurrent = () => api<BattleRound>("/user/battle/current");
export const battleBet = (side: BattleSide, amount_rub: number) =>
  api<BattleRound>("/user/battle/bet", { method: "POST", body: { side, amount_rub } });
export const battleHistory = (limit = 20) =>
  api<BattleHistoryItem[]>("/user/battle/history", { query: { limit } });
