// Admin panel API. All calls scope="admin". Loose types (known fields + index
// signature); render defensively. Contract mirrors routers/admin_*.py.
import { panelApi, getPanelToken, PanelApiError } from "@/panel/lib/panelApi";
import type { CasinoClientHistoryPage, CasinoClientProfile } from "@/panel/lib/casinoClientProfile";

type Opts = Omit<Parameters<typeof panelApi>[1], "scope">;
export const adm = <T>(path: string, opts: Opts = {}) => panelApi<T>(`/admin${path}`, { ...opts, scope: "admin" });

export type Dict = Record<string, unknown>;

// ---- dashboard / stats ----
export const dashLive = () => adm<Dict>("/dashboard/live");
export const dashLiabilities = () => adm<Dict>("/dashboard/liabilities");
export const dashOwner = (period: "today" | "yesterday" | "week" | "month" | "year" = "today") =>
  adm<Dict>("/dashboard/owner", { query: { period } });
export const dashWalletDaily = (date_from?: string, date_to?: string) => adm<Dict>("/dashboard/wallet-daily", { query: { date_from, date_to } });
export const dashVolumeCohorts = (mode = "lifetime", date_from?: string, date_to?: string) => adm<Dict>("/dashboard/volume-cohorts", { query: { mode, date_from, date_to } });
export const getStats = (date_from?: string, date_to?: string) => adm<Dict>("/stats", { query: { date_from, date_to } });
export const getVpnSummary = () => adm<Dict>("/vpn/summary");
export type VpnPlan = { code: string; title: string; days: number; price_rub: string };
export type VpnBillingSettings = {
  plans: VpnPlan[];
  device_addons: VpnPlan[];
  trial: { enabled: boolean; days: number; min_exchanges: number };
  purchase_min_exchanges: number;
  purchase_min_invited: number;
  app_url: string;
  review_bonus_text_rub: number;
  review_bonus_photo_rub: number;
};
export const getVpnSettings = () => adm<{ settings: VpnBillingSettings }>("/vpn/settings");
export const putVpnSettings = (settings: VpnBillingSettings) =>
  adm<{ settings: VpnBillingSettings }>("/vpn/settings", { method: "PUT", body: { settings } });
export const getVpnPurchases = (query: { status?: string; kind?: string; telegram_id?: string; offset?: number } = {}) =>
  adm<{ total: number; items: Dict[] }>("/vpn/purchases", { query: { limit: 50, ...query } });
export const getVpnReconciliation = () => adm<Dict>("/vpn/reconciliation");
export type VpnDevice = { id: string; name: string; platform: string; created_at: string; connected: boolean };
export type VpnUser = {
  telegram_id?: number;
  username?: string | null;
  first_name?: string | null;
  available_rub: number;
  exchanges: { have: number; need: number };
  purchase_open: boolean;
  trusted: boolean;
  trial: { enabled: boolean; days: number; min_exchanges: number; used: boolean };
  trial_available: boolean;
  subscription: { active: boolean; plan: string | null; status: string | null; ends_at: string | null; days_left: number };
  devices: VpnDevice[];
  purchases: Dict[];
  cp_error: string | null;
};
export const getVpnUser = (telegramId: string) => adm<VpnUser>(`/vpn/user/${encodeURIComponent(telegramId)}`);
export const resolveVpnUser = (q: string) =>
  adm<{ telegram_id: number; username: string | null; first_name: string | null }>("/vpn/resolve", { query: { q } });
export const revokeVpnDevice = (telegramId: string, deviceId: string) =>
  adm<{ ok: boolean }>(`/vpn/user/${encodeURIComponent(telegramId)}/devices/${encodeURIComponent(deviceId)}/revoke`, { method: "POST" });
export const setVpnTrusted = (telegramId: string, trusted: boolean) =>
  adm<{ telegram_id: number; trusted: boolean }>(`/vpn/user/${encodeURIComponent(telegramId)}/trusted`, { method: "POST", body: { trusted } });
export const getStatsPromo = (date_from?: string, date_to?: string) => adm<Dict>("/stats/promo", { query: { date_from, date_to } });
export const getPnl = () => adm<Dict>("/stats/pnl");
export const getFinanceOverview = (date_from?: string, date_to?: string) =>
  adm<Dict>("/finance-overview", { query: { date_from, date_to } });
export type AdminTrafficHour = {
  hour: number;
  orders: number;
  fiat_sum: number;
  paid_orders: number;
  paid_fiat_sum: number;
};
export type AdminTrafficBucket = { key: string; orders: number; fiat_sum: number };
export type AdminTrafficCountRow = { status?: string; source?: string; orders: number; fiat_sum: number };
export type AdminTrafficStats = {
  period: { from: string; to: string };
  timezone: "Europe/Moscow";
  summary: { orders: number; fiat_sum: number; paid_orders: number; paid_fiat_sum: number };
  by_hour: AdminTrafficHour[];
  amount_buckets: AdminTrafficBucket[];
  by_status: Array<AdminTrafficCountRow & { status: string }>;
  by_source: Array<AdminTrafficCountRow & { source: string }>;
};
export const getTrafficStats = (date_from?: string, date_to?: string) =>
  adm<AdminTrafficStats>("/traffic-stats", { query: { date_from, date_to } });
export const getMisses = (date_from?: string, date_to?: string) =>
  adm<Dict>("/misses", { query: { date_from, date_to } });

// ---- casino ----
export const ADMIN_CASINO_GAME_TYPES = [
  "pvp_dice",
  "baccara",
  "blackjack",
  "raffle",
  "cub",
  "roulette",
  "holdem",
  "jackpot",
  "fixed_room",
  "clan_war",
  "russian_draughts",
] as const;
export type AdminCasinoGameType = (typeof ADMIN_CASINO_GAME_TYPES)[number];
export type AdminCasinoGameStatus = "waiting" | "active" | "finished" | "cancelled" | "expired";
export type AdminCasinoWithdrawalStatus = "pending" | "approved" | "rejected" | "cancelled";
export type AdminCasinoWithdrawalMethod = "crypto" | "card" | "sbp";

export interface AdminCasinoDashboard {
  total_games: number;
  total_turnover_rub: number;
  total_commission_rub: number;
  owner_profit_rub: number;
  owner_commission_profit_rub?: number;
  house_game_profit_rub?: number;
  house_turnover_rub?: number;
  active_players_count: number;
  games_today: number;
  turnover_today_rub: number;
  commission_today_rub: number;
  games_by_type: Partial<Record<AdminCasinoGameType, number>>;
  top_players: Array<{
    telegram_id: number;
    username: string | null;
    games_count: number;
    total_bet: number;
  }>;
  top_clans?: Array<{
    id: number;
    tag: string;
    name: string;
    owner_id: number;
    member_count: number;
    wager_rub: number;
  }>;
}
export interface AdminCasinoChartPoint {
  date: string;
  games_count: number;
  turnover_rub: number;
  commission_rub: number;
  owner_profit_rub: number;
  owner_commission_profit_rub?: number;
  house_game_profit_rub?: number;
  house_turnover_rub?: number;
  ggr_rub?: number;
}

export type AdminCasinoRtpTone = "low" | "medium" | "high";

export interface AdminCasinoStatsVolume {
  handle_rub: number;
  player_payout_rub: number;
  ggr_rub: number;
  rake_rub: number;
  hold_pct: number | null;
  rtp_pct: number | null;
  rounds: number;
  avg_bet_rub: number | null;
  bot_backed_stake_rub: number;
}

export interface AdminCasinoStats {
  period: { from: string | null; to: string | null };
  volume: AdminCasinoStatsVolume;
  ggr_breakdown: {
    pvp_rake_rub: number;
    jackpot_rake_rub: number;
    rooms_rake_rub: number;
    house_vs_bots_rub: number;
  };
  costs: {
    cashback_rub: number;
    bonus_rub: number;
    creator_share_rub: number;
    referral_share_rub: number;
    total_rub: number;
  };
  ngr_rub: number;
  owner: {
    commission_profit_rub: number;
    house_game_profit_rub: number;
    owner_profit_rub: number;
  };
  reconciliation: { ggr_rub: number; owner_profit_rub: number; diff_rub: number };
  by_type: Array<{
    game_type: string;
    rounds: number;
    handle_rub: number;
    player_payout_rub: number;
    ggr_rub: number;
    rake_rub: number;
    hold_pct: number | null;
    rtp_pct: number | null;
    theoretical_rtp_pct: number | null;
    rtp_tone: AdminCasinoRtpTone | null;
  }>;
  daily: Array<{
    date: string;
    rounds: number;
    handle_rub: number;
    ggr_rub: number;
    rake_rub: number;
    owner_profit_rub: number;
  }>;
  players: {
    active: number;
    new: number;
    avg_handle_rub: number | null;
    top: Array<{
      telegram_id: number;
      username: string | null;
      rounds: number;
      handle_rub: number;
      payout_rub: number;
      net_rub: number;
    }>;
  };
  cashier: {
    deposited_rub: number;
    deposit_count: number;
    withdrawn_rub: number;
    pending_withdraw_rub: number;
  };
  bankroll: { balance_rub: number; reserved_rub: number; available_rub: number };
  top_clans: Array<{
    id: number;
    tag: string;
    name: string;
    owner_id: number;
    member_count: number;
    wager_rub: number;
  }>;
  distributions?: {
    referrals: AdminCasinoShareTable;
    creators: AdminCasinoShareTable;
    cashback: AdminCasinoShareTable;
    bonuses: AdminCasinoShareTable;
  };
}

export interface AdminCasinoShareRow {
  recipient_id: number | null;
  recipient_username: string | null;
  creator_account_id?: number | null;
  source_player_id: number | null;
  source_username: string | null;
  level: "l1" | "l2" | null;
  games: number;
  amount_rub: number;
}

export interface AdminCasinoShareTable {
  total_rub: number;
  shown_rub: number;
  hidden_count: number;
  hidden_rub: number;
  rows: AdminCasinoShareRow[];
}

export const getCasinoStats = (date_from?: string, date_to?: string) =>
  adm<AdminCasinoStats>("/casino/stats", { query: { date_from, date_to } });
export interface AdminCasinoGame {
  game_id: string;
  game_type: AdminCasinoGameType;
  created_at: string;
  finished_at: string | null;
  status: AdminCasinoGameStatus;
  players: number[];
  bet_amount_rub: number;
  winner_id: number | null;
  commission_rub: number;
  creator_cut_rub: number;
  owner_cut_rub: number;
}
export interface AdminCasinoGameDetail extends AdminCasinoGame {
  game_data: Record<string, unknown>;
}
export interface AdminCasinoGamesQuery {
  game_type?: AdminCasinoGameType;
  status?: AdminCasinoGameStatus;
  player_id?: number;
  limit?: number;
  offset?: number;
}
export interface AdminCasinoCommissionPreview {
  stake_rub: number;
  commission_rub: number;
  creator_rub: number;
  referral_l1_rub: number;
  referral_l2_rub: number;
  owner_rub: number;
}
export interface AdminCasinoSettings {
  commission_rate: number;
  creator_cut_percent: number;
  referral_l1_percent: number;
  referral_l2_percent: number;
  owner_share_percent: number;
  owner_share_percent_wagering_active: number;
  owner_share_percent_wagering_complete: number;
  wagering_percent: number;
  commission_rate_wagering_active: number;
  commission_rate_wagering_complete: number;
  creator_cut_percent_wagering_active: number;
  referral_l1_percent_wagering_active: number;
  referral_l2_percent_wagering_active: number;
  creator_cut_percent_wagering_complete: number;
  referral_l1_percent_wagering_complete: number;
  referral_l2_percent_wagering_complete: number;
  min_bet_rub: number;
  max_bet_rub: number;
  min_withdrawal_rub: number;
  max_profit_pct_per_round: number;
  max_profit_pct_per_round_all: number;
  bankroll_floor_rub: number;
  liability_amount_rub: number;
  per_game_limits: Partial<Record<AdminCasinoGameType, { min?: number; max?: number }>>;
  bet_step_rub: number;
  max_concurrent_games_per_player: number;
  max_rounds_per_player_per_day: Partial<Record<AdminCasinoGameType, number>>;
  pending_invite_ttl_minutes: number;
  move_timeout_minutes: number;
  holdem_small_blind_rub: number;
  holdem_big_blind_rub: number;
  holdem_rake_percent: number;
  holdem_rake_cap_rub: number;
  holdem_action_timeout_seconds: number;
  draughts_move_timeout_seconds: number;
  holdem_min_buyin_bb: number;
  holdem_max_buyin_bb: number;
  jackpot_collect_seconds: number;
  jackpot_max_players: number;
  jackpot_rake_percent: number;
  roulette_table_collect_seconds: number;
  roulette_table_max_players: number;
  clans_enabled: boolean;
  clan_max_members: number;
  fixed_room_rake_percent: number;
  fixed_room_max_seats: number;
  fixed_room_collect_seconds: number;
  clan_war_rake_percent: number;
  clan_war_max_fighters: number;
  clan_war_collect_seconds: number;
  commission_cap_rub: number;
  commission_min_rub: number;
  deposit_limit_enabled: boolean;
  loss_limit_enabled: boolean;
  wager_limit_enabled: boolean;
  session_limit_enabled: boolean;
  reality_check_default_minutes: number;
  self_exclusion_min_hours: number;
  timeout_max_hours: number;
  limit_loosening_delay_hours: number;
  withdrawal_auto_approve_max_rub: number;
  withdrawal_manual_review_min_rub: number;
  withdrawal_daily_limit_rub: number;
  withdrawal_hourly_limit_rub: number;
  provably_fair_enabled: Record<AdminCasinoGameType, boolean>;
  seed_rotation_allowed: boolean;
  enabled_games: Record<AdminCasinoGameType, boolean>;
  commission_preview: AdminCasinoCommissionPreview;
  commission_preview_wagering_active: AdminCasinoCommissionPreview;
  commission_preview_wagering_complete: AdminCasinoCommissionPreview;
  cashback_volume_tiers: Array<{ min_wager_rub: number; percent: number }>;
  commission_volume_tiers: Array<{ min_wager_rub: number; active_rate: number; complete_rate: number }>;
  level_reach_bonuses: Array<{ min_wager_rub: number; bonus_rub: number }>;
}
export interface AdminCasinoSettingsPatch {
  commission_rate?: number;
  creator_cut_percent?: number;
  referral_l1_percent?: number;
  referral_l2_percent?: number;
  wagering_percent?: number;
  commission_rate_wagering_active?: number;
  commission_rate_wagering_complete?: number;
  creator_cut_percent_wagering_active?: number;
  referral_l1_percent_wagering_active?: number;
  referral_l2_percent_wagering_active?: number;
  creator_cut_percent_wagering_complete?: number;
  referral_l1_percent_wagering_complete?: number;
  referral_l2_percent_wagering_complete?: number;
  min_bet_rub?: number;
  max_bet_rub?: number;
  min_withdrawal_rub?: number;
  max_profit_pct_per_round?: number;
  max_profit_pct_per_round_all?: number;
  bankroll_floor_rub?: number;
  liability_amount_rub?: number;
  per_game_limits?: Partial<Record<AdminCasinoGameType, { min?: number; max?: number }>>;
  bet_step_rub?: number;
  max_concurrent_games_per_player?: number;
  max_rounds_per_player_per_day?: Partial<Record<AdminCasinoGameType, number>>;
  pending_invite_ttl_minutes?: number;
  move_timeout_minutes?: number;
  holdem_small_blind_rub?: number;
  holdem_big_blind_rub?: number;
  holdem_rake_percent?: number;
  holdem_rake_cap_rub?: number;
  holdem_action_timeout_seconds?: number;
  draughts_move_timeout_seconds?: number;
  holdem_min_buyin_bb?: number;
  holdem_max_buyin_bb?: number;
  jackpot_collect_seconds?: number;
  jackpot_max_players?: number;
  jackpot_rake_percent?: number;
  roulette_table_collect_seconds?: number;
  roulette_table_max_players?: number;
  clans_enabled?: boolean;
  clan_max_members?: number;
  fixed_room_rake_percent?: number;
  fixed_room_max_seats?: number;
  fixed_room_collect_seconds?: number;
  clan_war_rake_percent?: number;
  clan_war_max_fighters?: number;
  clan_war_collect_seconds?: number;
  commission_cap_rub?: number;
  commission_min_rub?: number;
  deposit_limit_enabled?: boolean;
  loss_limit_enabled?: boolean;
  wager_limit_enabled?: boolean;
  session_limit_enabled?: boolean;
  reality_check_default_minutes?: number;
  self_exclusion_min_hours?: number;
  timeout_max_hours?: number;
  limit_loosening_delay_hours?: number;
  withdrawal_auto_approve_max_rub?: number;
  withdrawal_manual_review_min_rub?: number;
  withdrawal_daily_limit_rub?: number;
  withdrawal_hourly_limit_rub?: number;
  provably_fair_enabled?: Partial<Record<AdminCasinoGameType, boolean>>;
  seed_rotation_allowed?: boolean;
  enabled_games?: Partial<Record<AdminCasinoGameType, boolean>>;
  cashback_volume_tiers?: Array<{ min_wager_rub: number; percent: number }>;
  commission_volume_tiers?: Array<{ min_wager_rub: number; active_rate: number; complete_rate: number }>;
  level_reach_bonuses?: Array<{ min_wager_rub: number; bonus_rub: number }>;
  reason?: string;
}
export interface AdminCasinoSettingsAuditRow {
  id: number;
  batch_id: string;
  key: string;
  old_value: unknown;
  new_value: unknown;
  changed_by: string;
  changed_at: string;
  reason: string;
}
export interface AdminCasinoSettingsAuditList {
  items: AdminCasinoSettingsAuditRow[];
  total: number;
}
export interface AdminCasinoCreatorWithdrawal {
  withdrawal_id: number;
  created_at: string;
  amount_rub: number;
  method: AdminCasinoWithdrawalMethod;
  requisites: string;
  status: AdminCasinoWithdrawalStatus;
  processed_at: string | null;
  processed_by_admin_id: string | null;
  tx_hash: string | null;
  rejection_reason: string | null;
}
export interface AdminCasinoWithdrawalActionResult {
  success: boolean;
  message: string;
}
export interface AdminCasinoCreatorAccount {
  id: number;
  web_user_id: number;
  username: string | null;
  display_name: string | null;
  ref_token: string;
  ref_link: string;
  assigned_at: string;
}
export type AdminCasinoGameChatBindingStatus = "pending" | "active" | "disabled";
export interface AdminCasinoGameChatBinding {
  id: number;
  chat_id: number;
  chat_type: string;
  chat_title: string | null;
  telegram_url: string | null;
  status: AdminCasinoGameChatBindingStatus;
  requested_by_telegram_id: number;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  disabled_at: string | null;
}
export const getCasinoDashboard = () => adm<AdminCasinoDashboard>("/casino/dashboard");
export const disbandCasinoClan = (clanId: number) =>
  adm<{ ok: boolean; disbanded_tag: string }>(`/casino/clans/${clanId}/disband`, { method: "POST" });

export type AdminCasinoRiskWindow = "24h" | "7d" | "30d";
export type AdminCasinoRiskTone = "low" | "medium" | "high";
export interface AdminCasinoRiskPlayer {
  telegram_id: number;
  username: string | null;
  rounds: number;
  wager_rub: number;
  returned_rub: number;
  net_rub: number;
  player_rtp_pct: number | null;
  game_rtp_pct: number | null;
  delta_pp?: number;
  risk?: AdminCasinoRiskTone;
}
export interface AdminCasinoRisk {
  window: AdminCasinoRiskWindow;
  rtp_deviation_pp: number;
  verify: { label: string; value_rub: number; sql: string };
  bankroll: {
    balance_rub: number;
    reserved_rub: number;
    available_rub: number;
    floor_rub: number;
    target_rub: number;
    max_payout_rub: number;
    max_profit_pct_per_round: number;
  };
  exposure: {
    open_pvp_banks_rub: number;
    house_liability_rub: number;
    total_rub: number;
    pct_of_bank: number | null;
  };
  games: Array<{
    game_type: AdminCasinoGameType;
    rounds: number;
    wager_rub: number;
    returned_rub: number;
    actual_rtp_pct: number | null;
    theoretical_rtp_pct: number | null;
    corridor_low_pct: number;
    corridor_high_pct: number;
  }>;
  anomalies: AdminCasinoRiskPlayer[];
  winners: AdminCasinoRiskPlayer[];
  losers: AdminCasinoRiskPlayer[];
  commission_complete_percent: number;
}
export const getCasinoRisk = (query: { window?: AdminCasinoRiskWindow; rtp_deviation_pp?: number } = {}) =>
  adm<AdminCasinoRisk>("/casino/risk", { query });
export const getCasinoChart = (days = 30) =>
  adm<AdminCasinoChartPoint[]>("/casino/chart", { query: { days } });

export interface AdminCasinoHouseAccount {
  id: number;
  account_key: string;
  display_name: string;
  balance_rub: number;
  reserved_rub: number;
  available_rub: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}
export interface AdminCasinoHouseLedgerEntry extends Record<string, unknown> {
  id: number;
  account_id: number;
  game_id: string | null;
  entry_key: string;
  entry_type: "funding" | "adjustment" | "game_settlement" | "reservation_release";
  amount_rub: number;
  balance_after_rub: number;
  reason: string;
  created_by: string | null;
  created_at: string;
}
export interface AdminCasinoHouseProfile {
  id: number;
  profile_key: string;
  display_name: string;
  mode: "house_robot" | "pvp_robot";
  account_id: number;
  is_active: boolean;
  allowed_games: AdminCasinoGameType[];
  min_bet_rub: number;
  max_bet_rub: number;
  max_concurrent_games: number;
  max_exposure_rub: number;
  created_at?: string;
  updated_at?: string;
}
export interface AdminCasinoHousePolicy extends Record<string, unknown> {
  id: number;
  policy_key: string;
  version: number;
  game_type: AdminCasinoGameType;
  is_active: boolean;
  payout_multiplier: number;
  win_probability: number;
  terms: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
}
export interface AdminCasinoHouseMutation {
  amount_rub: number;
  reason: string;
  idempotency_key: string;
}
export interface AdminCasinoHouseProfilePatch {
  is_active?: boolean;
  display_name?: string;
  mode?: "house_robot" | "pvp_robot";
  allowed_games?: AdminCasinoGameType[];
  min_bet_rub?: number;
  max_bet_rub?: number;
  max_concurrent_games?: number;
  max_exposure_rub?: number;
}
export interface AdminCasinoHouseProfileCreate {
  profile_key: string;
  display_name: string;
  account_id?: number;
  mode?: "house_robot" | "pvp_robot";
  allowed_games?: AdminCasinoGameType[];
  min_bet_rub?: number;
  max_bet_rub?: number;
  max_concurrent_games?: number;
  max_exposure_rub?: number;
  is_active?: boolean;
}
export type AdminCasinoHouseReadinessStep =
  | "bank"
  | "profiles"
  | "limits"
  | "telegram"
  | "commission"
  | "games";
export interface AdminCasinoHouseReadinessCheck {
  id: string;
  ok: boolean;
  title: string;
  detail: string;
  step: AdminCasinoHouseReadinessStep | string;
  href?: string;
  required?: boolean;
}
export interface AdminCasinoHouseReadiness {
  ready: boolean;
  game_type: AdminCasinoGameType;
  stake_rub: number;
  recommended_stake_rub: number;
  max_bots_capacity: number;
  available_rub: number;
  active_pvp_profiles: number;
  checks: AdminCasinoHouseReadinessCheck[];
  required?: AdminCasinoHouseReadinessCheck[];
  secondary?: AdminCasinoHouseReadinessCheck[];
  required_ready?: boolean;
  required_ok?: number;
  required_total?: number;
  bankroll_floor_rub?: number;
}
export interface AdminCasinoHousePolicyCreate {
  policy_key: string;
  game_type: AdminCasinoGameType;
  payout_multiplier: number;
  win_probability: number;
  terms?: Record<string, unknown>;
}
export const getCasinoHouseAccounts = () =>
  adm<AdminCasinoHouseAccount[]>("/casino/house/accounts");
export const getCasinoHouseLedger = (accountId: number) =>
  adm<AdminCasinoHouseLedgerEntry[]>(`/casino/house/accounts/${accountId}/ledger`);
export const fundCasinoHouseAccount = (accountId: number, body: AdminCasinoHouseMutation) =>
  adm<AdminCasinoHouseAccount>(`/casino/house/accounts/${accountId}/fund`, { method: "POST", body });
export const adjustCasinoHouseAccount = (accountId: number, body: AdminCasinoHouseMutation) =>
  adm<AdminCasinoHouseAccount>(`/casino/house/accounts/${accountId}/adjust`, { method: "POST", body });
export const getCasinoHouseProfiles = () =>
  adm<AdminCasinoHouseProfile[]>("/casino/house/profiles");
export const getCasinoHouseReadiness = (query?: { game_type?: AdminCasinoGameType; stake_rub?: number }) =>
  adm<AdminCasinoHouseReadiness>("/casino/house/readiness", { query: { ...query } });
export const createCasinoHouseProfile = (body: AdminCasinoHouseProfileCreate) =>
  adm<AdminCasinoHouseProfile>("/casino/house/profiles", { method: "POST", body });
export const patchCasinoHouseProfile = (profileId: number, body: AdminCasinoHouseProfilePatch) =>
  adm<AdminCasinoHouseProfile>(`/casino/house/profiles/${profileId}`, { method: "PATCH", body });
export const getCasinoHousePolicies = () =>
  adm<AdminCasinoHousePolicy[]>("/casino/house/policies");
export const createCasinoHousePolicy = (body: AdminCasinoHousePolicyCreate) =>
  adm<AdminCasinoHousePolicy>("/casino/house/policies", { method: "POST", body });
export const activateCasinoHousePolicy = (policyId: number) =>
  adm<AdminCasinoHousePolicy>(`/casino/house/policies/${policyId}/activate`, { method: "POST" });
export const getCasinoGames = (query: AdminCasinoGamesQuery = {}) =>
  adm<AdminCasinoGame[]>("/casino/games", { query: { ...query } });
export const getCasinoGame = (gameId: string) =>
  adm<AdminCasinoGameDetail>(`/casino/games/${encodeURIComponent(gameId)}`);
export const getCasinoPlayerProfile = (playerId: number | string) =>
  adm<CasinoClientProfile>(`/casino/players/${playerId}/profile`);
export const getCasinoPlayerHistory = (
  playerId: number | string,
  query: { before?: string; game_type?: string } = {},
) => adm<CasinoClientHistoryPage>(`/casino/players/${playerId}/history`, { query });
export const getCasinoSettings = () => adm<AdminCasinoSettings>("/casino/settings");
export const getCasinoSettingsAudit = (query?: {
  date_from?: string;
  date_to?: string;
  window?: "24h" | "7d" | "30d";
  key?: string;
  changed_by?: string;
  q?: string;
  batch_id?: string;
  limit?: number;
  offset?: number;
}) => adm<AdminCasinoSettingsAuditList>("/casino/settings/audit", { query });
export const patchCasinoSettings = (body: AdminCasinoSettingsPatch) =>
  adm<AdminCasinoSettings>("/casino/settings", { method: "PATCH", body });
export const getCasinoCreatorAccount = () =>
  adm<AdminCasinoCreatorAccount | null>("/casino/creator/current");
export const assignCasinoCreatorAccount = (webUserId: number) =>
  adm<AdminCasinoCreatorAccount>("/casino/creator/assign", {
    method: "POST",
    body: { web_user_id: webUserId },
  });
export const revokeCasinoCreatorAccount = () =>
  adm<{ success: boolean }>("/casino/creator/revoke", { method: "POST" });
export interface AdminCasinoBotStatus {
  configured: boolean;
  username: string | null;
  deep_link: string | null;
}
export const getCasinoBotStatus = () =>
  adm<AdminCasinoBotStatus>("/casino/bot-status");
export const getCasinoGameChatBinding = () =>
  adm<AdminCasinoGameChatBinding | null>("/casino/chat-binding");
export const confirmCasinoGameChatBinding = (bindingId: number) =>
  adm<AdminCasinoGameChatBinding>("/casino/chat-binding/confirm", {
    method: "POST",
    body: { binding_id: bindingId },
  });
export const disableCasinoGameChatBinding = (bindingId: number) =>
  adm<AdminCasinoGameChatBinding>("/casino/chat-binding/disable", {
    method: "POST",
    body: { binding_id: bindingId },
  });
export const getCasinoCreatorWithdrawals = (status?: AdminCasinoWithdrawalStatus) =>
  adm<AdminCasinoCreatorWithdrawal[]>("/casino/creator/withdrawals", { query: { status } });
export const approveCasinoCreatorWithdrawal = (withdrawalId: number, txHash: string) =>
  adm<AdminCasinoWithdrawalActionResult>(
    `/casino/creator/withdrawals/${withdrawalId}/approve`,
    { method: "POST", body: { tx_hash: txHash.trim() } },
  );
export const rejectCasinoCreatorWithdrawal = (withdrawalId: number, reason: string) =>
  adm<AdminCasinoWithdrawalActionResult>(
    `/casino/creator/withdrawals/${withdrawalId}/reject`,
    { method: "POST", body: { reason: reason.trim() } },
  );

// ---- orders ----
export interface AdminOrder {
  order_id: string;
  status: string;
  status_label?: string;
  direction: string;
  crypto: string;
  crypto_amount?: number;
  fiat_amount?: number;
  rate?: number;
  user_id?: number;
  buyer_username?: string;
  buyer_first_name?: string;
  buyer_avatar_url?: string | null;
  operator_name?: string;
  origin?: string;
  order_source?: string;
  source_label?: string;
  has_receipt?: boolean;
  receipt_kind?: string | null;
  required_receipt_type?: number | null;
  requisites?: string;
  wallet_address?: string;
  network?: string;
  created_at?: string;
  referrer_user_id?: number | null;
  referrer_username?: string | null;
  referrer_first_name?: string | null;
  service_profit_rub?: number;
  payout_tx_hash?: string | null;
  cancel_reason?: string | null;
  autopay_preview?: AutopayPreview;
  [k: string]: unknown;
}

export interface AutopayCheck { key: string; ok: boolean; pending?: boolean; detail?: string }
export interface AutopayStep { key: string; state: "done" | "now" | "wait" | "block" | string; text: string }
export interface AutopayMoment {
  key: string;
  headline: string;
  send_text?: string;
  blockers?: string[];
  steps: AutopayStep[];
}
export interface AutopayPreview {
  verdict: "auto" | "waiting" | "manual" | "n/a";
  reasons: string[];
  checks: AutopayCheck[];
  toggles?: { mode?: boolean; no_shift?: boolean; payout?: boolean };
  live_checks?: AutopayCheck[];
  live_blocked?: string[];
  moment?: AutopayMoment;
}
export interface AdminPartnerOption { id: number; label: string }
export const getOrders = (q: Dict = {}) =>
  adm<{ orders: AdminOrder[]; total: number; limit: number; offset: number; partner_options?: AdminPartnerOption[] }>("/orders", { query: q });
export const getOrder = (id: string) => adm<AdminOrder>(`/orders/${id}`);
export const setOrderStatus = (id: string, status: string) => adm<Dict>(`/orders/${id}/status`, { method: "PATCH", body: { status } });
export const syncCryptoToPayin = (id: string) => adm<Dict>(`/orders/${id}/sync-crypto-to-payin`, { method: "POST" });
export const confirmAdminPayout = (id: string, txHash: string) =>
  adm<Dict>(`/orders/${id}/payout`, { method: "POST", body: { tx_hash: txHash } });
export const cancelAdminOrder = (id: string, reason: string) =>
  adm<Dict>(`/orders/${id}/cancel`, { method: "POST", body: { reason } });

export type VerificationSeverity = "ok" | "warn" | "danger";
export interface VerificationCheck {
  key: string;
  label: string;
  severity: VerificationSeverity | string;
  points?: number;
  detail?: string | null;
}
export interface ReceiptInfo {
  has: boolean;
  kind: "pdf" | "video" | "other" | null;
  filename?: string | null;
  requested_at?: string | null;
  submitted_at?: string | null;
  upload_sec?: number | null;
  sha256?: string | null;
  pdf_meta?: {
    producer?: string | null;
    creator?: string | null;
    creation_date?: string | null;
    page_kind?: string | null;
    size?: unknown;
    amount_present?: unknown;
    flags?: string[];
  } | null;
  ops_pending?: boolean;
}
export interface ReuseHit {
  user_id?: number | null;
  username?: string | null;
  order_id?: string | null;
  status?: string | null;
}
export interface OrderVerification {
  receipt: ReceiptInfo;
  risk: {
    score: number;
    level: string | null;
    items: VerificationCheck[];
    breakdown?: Record<string, number>;
  };
  checks: VerificationCheck[];
  client: {
    account_review_status?: string;
    account_review_reason?: string | null;
    device_review_status?: string;
    device_review_reason?: string | null;
    is_banned?: boolean;
    ban_type?: string | null;
    ban_reason?: string | null;
    paid_count?: number | null;
  };
  device: {
    ip?: string | null;
    fingerprint_short?: string | null;
    platform?: string | null;
    screen?: string | null;
    timezone?: string | null;
    fp_reuse?: boolean;
    fp_common?: boolean;
    fp_user_count?: number | null;
    ip_reuse?: boolean;
  };
  reuse: {
    wallet: ReuseHit[];
    ip: ReuseHit[];
    fingerprint: ReuseHit[];
    receipt_hash: ReuseHit[];
    available: boolean;
  };
  timeline: { key: string; label: string; at: string }[];
  payout_audit?: {
    crypto_ok?: boolean;
    crypto_cap?: number | null;
    expected_crypto?: number;
    service_profit_rub?: number;
  } | null;
}
export const getOrderVerification = (id: string) => adm<OrderVerification>(`/orders/${id}/verification`);
export async function fetchOrderReceiptBlob(orderId: string): Promise<{ url: string; type: string }> {
  const token = getPanelToken("admin");
  const res = await fetch(`/api/admin/orders/${encodeURIComponent(orderId)}/receipt`, {
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

// ---- users ----
export const getUsers = (q: Dict = {}) => adm<{ users: Dict[]; [k: string]: unknown }>("/users", { query: q });
export const getUserDetail = (id: number | string) => adm<Dict>(`/users/${id}`);

// ---- balances ----
export const getBalances = (min_rub = 1, user_limit = 100) => adm<Dict>("/balances", { query: { min_rub, user_limit } });

// ---- pricing ----
export const getPricing = () => adm<Dict>("/pricing-settings");
export const patchPricing = (body: Dict) => adm<Dict>("/pricing-settings", { method: "PATCH", body });
export const getTriangleOverview = (date_from: string, date_to: string) =>
  adm<Dict>("/triangle-overview", { query: { date_from, date_to } });

export const getAutopilot = () => adm<Dict>("/autopilot-settings");
export const patchAutopilot = (body: Dict) =>
  adm<Dict>("/autopilot-settings", { method: "PATCH", body });
export const getAutopilotOverview = () => adm<Dict>("/autopilot/overview");
export const getAutopilotFunds = () => adm<Dict>("/autopilot/funds");
export const trustAutopilotTopup = (txid: string, note = "") =>
  adm<Dict>("/autopilot/topups", { method: "POST", body: { txid, note } });
export const requeueAutopilotOrder = (orderId: string) =>
  adm<Dict>(`/autopilot/orders/${encodeURIComponent(orderId)}/requeue`, { method: "POST" });
export const rotateAutopilotAddress = (coin: string) =>
  adm<Dict>("/autopilot/deposit-address", { method: "POST", body: { coin } });

// Совпадает с USDT_EARN_PAD / FROZEN_USDT_PAD в routers/public.py.
// Публичный market уже с этим падом; для долларов его снимаем, пока обзор не отдал сырой курс.
const USDT_BUY_PAD_RUB = 2;
const USDT_FROZEN_PAD_RUB = 0.5;

/** Сырой USDT/RUB. 0 = курса нет. */
export const getUsdRateRub = async (): Promise<number> => {
  const r = await panelApi<Dict>("/public/rates", { scope: "admin" });
  const rates = (r.rates ?? {}) as Dict;
  const usdt = (rates.usdt ?? {}) as Dict;
  const market = Number(usdt.market);
  if (!Number.isFinite(market) || market <= 0) return 0;
  const pad = r.frozen === true ? USDT_BUY_PAD_RUB + USDT_FROZEN_PAD_RUB : USDT_BUY_PAD_RUB;
  const raw = Math.round((market - pad) * 100) / 100;
  return raw > 0 ? raw : market;
};

// ---- operators ----
export const getOperators = (q: Dict = {}) => adm<{ operators: Dict[]; can_view_finance?: boolean; [k: string]: unknown }>("/operators", { query: q });
export const createOperator = (body: Dict) => adm<Dict>("/operators", { method: "POST", body });
export const patchOperator = (id: number, body: Dict) => adm<Dict>(`/operators/${id}`, { method: "PATCH", body });
export const getOperatorStats = (id: number, q: Dict = {}) => adm<Dict>(`/operators/${id}/stats`, { query: q });
export const getOperatorSla = (id: number, days = 30) => adm<Dict>(`/operators/${id}/sla`, { query: { days } });
export const postOperatorPenalty = (id: number, body: { amount_rub: number; reason: string }) =>
  adm<Dict>(`/operators/${id}/penalty`, { method: "POST", body });
export const getOperatorShifts = (q: Dict = {}) => adm<{ shifts: Dict[]; [k: string]: unknown }>("/operators/shifts", { query: q });
export const closeOperatorShift = (id: number) => adm<Dict>(`/operators/${id}/shift/close`, { method: "POST" });

// ---- operator payroll pool ----
export const getOperatorPayrollSettings = () => adm<Dict>("/operator-payroll/settings");
export const patchOperatorPayrollSettings = (body: Dict) => adm<Dict>("/operator-payroll/settings", { method: "PATCH", body });
export const getOperatorPayrollGrades = () => adm<Dict>("/operator-payroll/grades");
export const patchOperatorPayrollGrades = (body: Dict) => adm<Dict>("/operator-payroll/grades", { method: "PATCH", body });
export const getOperatorPayrollDistribution = () => adm<Dict>("/operator-payroll/distribution");
export const getOperatorPayrollSplits = (q: Dict = {}) => adm<{ splits: Dict[]; [k: string]: unknown }>("/operator-payroll/splits", { query: q });
export const getPayrollPoolBalance = () => adm<Dict>("/operator-payroll/balance");

export const getPayoutRequests = (status = "pending", limit = 50) => adm<{ requests: Dict[]; [k: string]: unknown }>("/operator-payroll/requests", { query: { status, limit } });
export const payoutRequestPaid = (id: number, note?: string) => adm<Dict>(`/operator-payroll/requests/${id}/paid`, { method: "POST", body: { note } });
export const payoutRequestReject = (id: number, note?: string) => adm<Dict>(`/operator-payroll/requests/${id}/reject`, { method: "POST", body: { note } });

// ---- salary settings ----
export const getPayrollSettings = () => adm<Dict>("/payroll-settings");
export const patchPayrollSettings = (admin_weekly_salary_rub: number) => adm<Dict>("/payroll-settings", { method: "PATCH", body: { admin_weekly_salary_rub } });
export const patchSalaryRecipient = (id: number, body: Dict) => adm<Dict>(`/payroll/salary-recipients/${id}`, { method: "PATCH", body });
export const accrueSalary = (recipient_id?: number) => adm<Dict>("/payroll/salary-accrue", { method: "POST", query: { recipient_id } });

// ---- expenses ----
export const getExpenses = (category?: string, limit = 100) => adm<{ expenses?: Dict[]; [k: string]: unknown } | Dict[]>("/manual-expenses", { query: { category, limit } });
export const createExpense = (body: Dict) => adm<Dict>("/manual-expenses", { method: "POST", body });
export const patchExpense = (id: number, body: Dict) => adm<Dict>(`/manual-expenses/${id}`, { method: "PATCH", body });
export const deleteExpense = (id: number) => adm<Dict>(`/manual-expenses/${id}`, { method: "DELETE" });

// ---- recurring expenses ----
export const getRecurringExpenses = (category?: string, is_active?: boolean, limit = 200) =>
  adm<{ expenses: Dict[]; [k: string]: unknown }>("/recurring-expenses", { query: { category, is_active, limit } });
export const getUpcomingExpenses = (days = 7) =>
  adm<{ expenses: Dict[]; days: number; until: string }>("/recurring-expenses/upcoming", { query: { days } });
export const getRoiAnalysis = (period_days = 30) =>
  adm<{ expenses: Dict[]; period_days: number; date_from: string; date_to: string; threshold_roi: number }>("/recurring-expenses/roi-analysis", { query: { period_days } });
export const createRecurringExpense = (body: Dict) => adm<Dict>("/recurring-expenses", { method: "POST", body });
export const patchRecurringExpense = (id: number, body: Dict) => adm<Dict>(`/recurring-expenses/${id}`, { method: "PATCH", body });
export const deleteRecurringExpense = (id: number) => adm<Dict>(`/recurring-expenses/${id}`, { method: "DELETE" });
export const billRecurringExpense = (id: number) => adm<Dict>(`/recurring-expenses/${id}/bill`, { method: "POST" });

// ---- promo ----
export const getPromos = () => adm<{ promos?: Dict[]; [k: string]: unknown } | Dict[]>("/promos");
export const getPromo = (id: number) => adm<Dict>(`/promos/${id}`);
export const createPromo = (body: Dict) => adm<Dict>("/promos", { method: "POST", body });
export const createFixedRubPromo = (body: Dict) => adm<Dict>("/promos/fixed-rub", { method: "POST", body });
export const createExchangeDiscount = (body: Dict) => adm<Dict>("/promos/exchange-discount", { method: "POST", body });
export const promoPayout = (id: number, amount_rub: number, note?: string) => adm<Dict>(`/promos/${id}/payout`, { method: "POST", body: { amount_rub, note } });
export const patchPromo = (id: number, body: Dict) => adm<Dict>(`/promos/${id}`, { method: "PATCH", body });
export const deletePromo = (id: number) => adm<Dict>(`/promos/${id}`, { method: "DELETE" });
export const quickPartner = (body: Dict) => adm<Dict>("/partners/quick", { method: "POST", body });

// ---- referral partners ----
export const getTierSettings = () => adm<Dict>("/referral-partners/tier-settings");
export const patchTierSettings = (body: Dict) => adm<Dict>("/referral-partners/tier-settings", { method: "PATCH", body });
export const getPartners = () => adm<{ partners?: Dict[]; [k: string]: unknown } | Dict[]>("/referral-partners");
export const patchPartner = (id: number, body: Dict) => adm<Dict>(`/referral-partners/${id}`, { method: "PATCH", body });
export const resetPartnerPassword = (id: number) => adm<Dict>(`/referral-partners/${id}/reset-password`, { method: "POST" });
export const partnerPayout = (id: number, amount_rub: number, note?: string) => adm<Dict>(`/referral-partners/${id}/payout`, { method: "POST", body: { amount_rub, note } });
export const getPartnerWithdrawals = (id: number) => adm<{ withdrawals?: Dict[]; [k: string]: unknown } | Dict[]>(`/referral-partners/${id}/withdrawals`);
export const partnerWithdrawalPaid = (id: number, source: string, payout_tx_hash?: string) => adm<Dict>(`/referral-partners/withdrawals/${id}/paid`, { method: "POST", query: { source }, body: { payout_tx_hash } });
export const partnerWithdrawalReject = (id: number, source: string, reason?: string) => adm<Dict>(`/referral-partners/withdrawals/${id}/reject`, { method: "POST", query: { source }, body: { reason } });

// ---- raffle / FocusLucky ----
export const getRaffle = () => adm<Dict>("/raffle");
export const getRaffleCampaigns = () => adm<{ campaigns?: Dict[] }>("/raffle/campaigns");
export const getRafflePartners = (q: Dict = {}) => adm<Dict>("/raffle/partners", { query: q });
export const getRaffleParticipants = (q: Dict = {}) => adm<Dict>("/raffle/participants", { query: q });
export const getRaffleParticipant = (userId: number) => adm<Dict>(`/raffle/participants/${userId}`);
export const patchRaffleText = (body: Dict) => adm<Dict>("/raffle/text", { method: "PATCH", body });
export const patchRafflePrizes = (places: Dict[]) => adm<Dict>("/raffle/prizes", { method: "PATCH", body: { places } });
export const patchRaffleShowSettings = (body: Dict) => adm<Dict>("/raffle/show-settings", { method: "PATCH", body });
export const patchRaffleDrawAt = (draw_at: string) => adm<Dict>("/raffle/draw-at", { method: "PATCH", body: { draw_at } });
export const patchRaffleSchedule = (body: { starts_at?: string; draw_at?: string }) =>
  adm<Dict>("/raffle/schedule", { method: "PATCH", body });
export const raffleAction = (action: "close" | "activate" | "start-new-without-draw" | "start-next" | "draw" | "pay-balance" | "start-show") => adm<Dict>(`/raffle/${action}`, { method: "POST" });
export const createRaffle = (body: { kind: "weekly" | "monthly"; draw_at: string }) =>
  adm<Dict>("/raffle/create", { method: "POST", body });
export const raffleBlockParticipant = (userId: number, scope: "all" | "referral" = "all") => adm<Dict>(`/raffle/participants/${userId}/block`, { method: "POST", body: { scope } });
export const raffleUnblockParticipant = (userId: number) => adm<Dict>(`/raffle/participants/${userId}/block`, { method: "DELETE" });
export const raffleBlockPartner = (userId: number) => adm<Dict>(`/raffle/partners/${userId}/block`, { method: "POST" });
export const raffleUnblockPartner = (userId: number) => adm<Dict>(`/raffle/partners/${userId}/block`, { method: "DELETE" });

// ---- casino tournaments ----
export const getCasinoTournaments = () => adm<{ tournaments?: Dict[] }>("/casino/tournaments");
export const createCasinoTournament = (body: Dict) => adm<Dict>("/casino/tournaments", { method: "POST", body });
export const patchCasinoTournament = (id: number, body: Dict) => adm<Dict>(`/casino/tournaments/${id}`, { method: "PATCH", body });
export const setCasinoTournamentStatus = (id: number, status: string) =>
  adm<Dict>(`/casino/tournaments/${id}/status/${status}`, { method: "POST" });
export const getCasinoTournamentParticipants = (id: number) =>
  adm<{ participants?: Dict[] }>(`/casino/tournaments/${id}/participants`);
export const blockCasinoTournamentParticipant = (id: number, user_id: number, blocked: boolean) =>
  adm<Dict>(`/casino/tournaments/${id}/block`, { method: "POST", body: { user_id, blocked } });
export const getCasinoTournamentAccess = (id: number) =>
  adm<{ access?: Dict[] }>(`/casino/tournaments/${id}/access`);
export const grantCasinoTournamentAccess = (id: number, identity: string, note: string) =>
  adm<{ access?: Dict[] }>(`/casino/tournaments/${id}/access`, { method: "POST", body: { identity, note } });
export const revokeCasinoTournamentAccess = (id: number, user_id: number) =>
  adm<{ access?: Dict[] }>(`/casino/tournaments/${id}/access/${user_id}`, { method: "DELETE" });

// ---- external ----
export const getExternalExchangers = (include_inactive = false) => adm<{ exchangers?: Dict[]; [k: string]: unknown } | Dict[]>("/external/exchangers", { query: { include_inactive } });
export const getExternalSummary = () => adm<Dict>("/external/summary");
export const createExchanger = (body: Dict) => adm<Dict>("/external/exchangers", { method: "POST", body });
export const getExchanger = (id: number) => adm<Dict>(`/external/exchangers/${id}`);
export const patchExchanger = (id: number, body: Dict) => adm<Dict>(`/external/exchangers/${id}`, { method: "PATCH", body });
export const issueExchangerCredentials = (id: number, username: string) => adm<Dict>(`/external/exchangers/${id}/issue-credentials`, { method: "POST", body: { username } });
export const resetExchangerPassword = (id: number) => adm<Dict>(`/external/exchangers/${id}/reset-password`, { method: "POST" });
export const getExchangerAccounts = (id: number) => adm<{ items?: Dict[] }>(`/external/exchangers/${id}/accounts`);
export const createExchangerClerk = (id: number, body: { username: string; label?: string }) =>
  adm<{ account?: Dict; credentials?: Dict }>(`/external/exchangers/${id}/accounts`, { method: "POST", body });
export const resetExchangerAccountPassword = (id: number, accountId: number) =>
  adm<Dict>(`/external/exchangers/${id}/accounts/${accountId}/reset-password`, { method: "POST" });
export const patchExchangerAccount = (id: number, accountId: number, body: Dict) =>
  adm<{ account?: Dict }>(`/external/exchangers/${id}/accounts/${accountId}`, { method: "PATCH", body });
export const getExchangerApiKey = (id: number) => adm<{ key?: Dict | null }>(`/external/exchangers/${id}/api-keys`);
export const issueExchangerApiKey = (id: number) => adm<Dict>(`/external/exchangers/${id}/api-keys`, { method: "POST" });
export const revokeExchangerApiKey = (id: number) =>
  adm<{ ok?: boolean; revoked?: boolean }>(`/external/exchangers/${id}/api-keys/revoke`, { method: "POST" });
export const getExchangerDeals = (id: number, q: Dict = {}) => adm<{ deals?: Dict[]; total?: number; [k: string]: unknown } | Dict[]>(`/external/exchangers/${id}/deals`, { query: q });
export const getExchangerLedger = (id: number, q: Dict = {}) => adm<{ entries?: Dict[]; balance_usd?: number; total?: number; [k: string]: unknown }>(`/external/exchangers/${id}/ledger`, { query: q });
export const getExchangerHistory = (id: number, q: Dict = {}) => adm<{ items?: Dict[]; total?: number }>(`/external/exchangers/${id}/history`, { query: q });
export const getExchangerPayouts = (id: number, q: Dict = {}) => adm<{ payouts?: Dict[]; total?: number }>(`/external/exchangers/${id}/payouts`, { query: q });
export const getExchangerStats = (id: number, q: Dict = {}) => adm<Dict>(`/external/exchangers/${id}/stats`, { query: q });
export const getExternalDeal = (dealId: number) => adm<Dict>(`/external/deals/${dealId}`);
export const createExchangerPayout = (id: number, body: Dict) => adm<Dict>(`/external/exchangers/${id}/payouts`, { method: "POST", body });
export async function fetchExchangerDealReceiptBlob(dealId: number): Promise<{ url: string; type: string }> {
  const token = getPanelToken("admin");
  const res = await fetch(`/api/admin/external/deals/${dealId}/receipt`, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new PanelApiError(
      res.status === 404 ? "Чек по сделке не найден" : "Не удалось открыть чек",
      res.status,
      null,
    );
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type || "application/octet-stream" };
}
export const getPendingPayouts = () => adm<{ payouts?: Dict[]; [k: string]: unknown } | Dict[]>("/external/payouts/pending");
export const completePayout = (id: number, body: Dict) => adm<Dict>(`/external/payouts/${id}/complete`, { method: "POST", body });
export const rejectPayout = (id: number, reason?: string) => adm<Dict>(`/external/payouts/${id}/reject`, { method: "POST", body: { reason } });

// ---- USDT issuance ----
export const getUsdtContext = () => adm<Dict>("/finance/operators-usdt-context");
export const issueUsdt = (operator_id: number, amount_usdt: number, note?: string) => adm<Dict>("/finance/usdt-issuance", { method: "POST", body: { operator_id, amount_usdt, note } });
export const getUsdtIssuances = (q: Dict = {}) => adm<{ issuances?: Dict[]; [k: string]: unknown } | Dict[]>("/finance/usdt-issuances", { query: q });

// ---- exchanger telegram bot ----
export const getExchangerBot = () => adm<Dict>("/exchanger-bot");
export const putExchangerBotToken = (token: string) => adm<Dict>("/exchanger-bot/token", { method: "PUT", body: { token } });
export const reconfigureExchangerBot = () => adm<Dict>("/exchanger-bot/reconfigure", { method: "POST" });
export const deleteExchangerBotToken = () => adm<Dict>("/exchanger-bot/token", { method: "DELETE" });
export const getExchangerBotMembers = () => adm<{ items?: Dict[] }>("/exchanger-bot/members");
export const createExchangerBotMember = (body: Dict) => adm<Dict>("/exchanger-bot/members", { method: "POST", body });
export const patchExchangerBotMember = (id: number, body: Dict) => adm<Dict>(`/exchanger-bot/members/${id}`, { method: "PATCH", body });
export const deleteExchangerBotMember = (id: number) => adm<Dict>(`/exchanger-bot/members/${id}`, { method: "DELETE" });
export const previewExchangerBotBroadcast = (audience: string) => adm<Dict>("/exchanger-bot/broadcast/preview", { query: { audience } });
export const createExchangerBotBroadcast = (body: { audience: string; text: string }) =>
  adm<Dict>("/exchanger-bot/broadcast", { method: "POST", body });
export const listExchangerBotBroadcasts = () => adm<{ items?: Dict[] }>("/exchanger-bot/broadcast");
export const cancelExchangerBotBroadcast = (id: number) => adm<Dict>(`/exchanger-bot/broadcast/${id}/cancel`, { method: "POST" });

// ---- security ----
export const getSecurityEvents = (q: Dict = {}) => adm<{ events?: Dict[]; [k: string]: unknown } | Dict[]>("/security/events", { query: q });
export const getSecurityStats = (hours = 24) => adm<Dict>("/security/events/stats", { query: { hours } });
export const getSecurityBans = () => adm<{ items?: Dict[] } & Dict>("/security/bans");
export const banSecurityIp = (ip: string, duration_sec = 3600, reason = "manual_admin") =>
  adm<Dict>("/security/bans", { method: "POST", body: { ip, duration_sec, reason } });
export const unbanSecurityIp = (ip: string) => adm<Dict>("/security/unban", { method: "POST", body: { ip } });
export const unbanSecurityEvent = (eventId: string) =>
  adm<Dict>("/security/unban", { method: "POST", body: { event_id: eventId } });
export const getSecurityLockdownHint = () => adm<Dict>("/security/lockdown", { method: "POST" });
export const exportSecurityEventsUrl = (hours = 24, brute_only = false) =>
  `/api/admin/security/events/export?hours=${hours}&brute_only=${brute_only ? "true" : "false"}`;

// ---- Ops AI tasks (dev review) ----
export interface AdminAiTask {
  id: number;
  title: string;
  request_text: string;
  status: string;
  priority?: string;
  summary?: string;
  file_list?: string[];
  freeze_hit?: boolean;
  cursor_prompt?: string;
  smoke_plan?: string;
  risks?: string;
  reject_reason?: string;
  operator_id?: number;
  created_at?: string;
  updated_at?: string;
  attachments?: { index: number; name?: string; content_type?: string; size?: number }[];
  agents?: {
    enabled?: boolean;
    triage?: { zones?: string[]; file_hints?: string[]; brief?: string };
    merged?: { role?: string; severity?: string; text?: string; files?: string[]; status?: string; kind?: string }[];
    selfcheck?: AiSelfcheckBlock;
    roles?: string[];
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
export const aiTasksPendingCount = () => adm<{ count: number }>("/ai-tasks/pending-count");
export const aiListTasks = (status = "review", page = 1) =>
  adm<{ tasks: AdminAiTask[]; total: number }>("/ai-tasks", {
    query: { status, page },
    cache: "no-store",
  });
export const aiGetTask = (id: number) => adm<AdminAiTask>(`/ai-tasks/${id}`);
export const aiTaskAttachmentUrl = (id: number, index: number) =>
  `/api/admin/ai-tasks/${id}/attachments/${index}`;
export const aiApproveTask = (id: number) =>
  adm<AdminAiTask>(`/ai-tasks/${id}/approve`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
export const aiRejectTask = (id: number, reason?: string) =>
  adm<AdminAiTask>(`/ai-tasks/${id}/reject`, {
    method: "POST",
    body: { reason },
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
export const aiDoneTask = (id: number, note?: string) =>
  adm<AdminAiTask>(`/ai-tasks/${id}/done`, {
    method: "POST",
    body: { note },
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });

// ---- UI regression agent (read-only, /x8/ai-tasks) ----
export type AiRegressionStep = {
  step: string;
  action: string;
  expected: string;
  actual: string;
  ok: boolean;
  severity?: string;
  screenshot?: string | null;
  bugfix_proposal?: string | null;
  console_errors?: string[];
  network_errors?: string[];
};
export type AiRegressionReport = {
  run_id: string;
  path: string;
  hint: string;
  deployment?: Record<string, unknown>;
  status: string;
  started_at?: string;
  finished_at?: string | null;
  steps: AiRegressionStep[];
  summary: string;
  max_severity?: string;
  agent_capabilities?: Record<string, unknown>;
  notes?: string[];
};
export type AiRegressionRun = {
  id: string;
  admin_id?: number;
  status: string;
  deployment?: Record<string, unknown>;
  report?: AiRegressionReport | null;
  capabilities?: Record<string, unknown>;
  [k: string]: unknown;
};
export const aiRegressionStart = (body: Record<string, unknown> = {}) =>
  adm<{ run: AiRegressionRun; replay?: boolean }>("/ai-tasks/regression/start", {
    method: "POST",
    body,
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
export const aiRegressionLatest = () =>
  adm<{ run: AiRegressionRun | null; capabilities?: Record<string, unknown> }>(
    "/ai-tasks/regression/latest",
  );
export const aiRegressionReport = (runId: string) =>
  adm<AiRegressionReport>(`/ai-tasks/regression/${encodeURIComponent(runId)}/report`);
export const aiRegressionObservations = (runId: string, body: Record<string, unknown>) =>
  adm<{ run: AiRegressionRun }>(
    `/ai-tasks/regression/${encodeURIComponent(runId)}/observations`,
    { method: "POST", body },
  );

// ---- Nightly SAST self-check (bandit / pip-audit) ----
export type AiSelfcheckCheck = {
  tool?: string;
  target?: string;
  version?: string | null;
  status?: string;
  reason?: string | null;
  exit_code?: number | null;
  timestamp?: string;
  artifact_rel?: string | null;
  finding_count?: number;
};
export type AiSelfcheckBlock = {
  run_id?: number | null;
  job_status?: string;
  exit_code?: number | null;
  source?: string;
  started_at?: string;
  finished_at?: string | null;
  artifact_rel?: string | null;
  checks?: AiSelfcheckCheck[];
};
export type AiSelfcheckRun = {
  id?: number;
  job_status?: string;
  exit_code?: number | null;
  started_at?: string;
  finished_at?: string | null;
  checks?: AiSelfcheckCheck[];
  artifact_rel?: string | null;
  source?: string;
  task_id?: number | null;
  alarm?: boolean;
  [k: string]: unknown;
};
export const aiSelfcheckLatest = () =>
  adm<{ run: AiSelfcheckRun | null }>("/ai-tasks/selfcheck/latest", { cache: "no-store" });
export const aiSelfcheckGet = (id: number) =>
  adm<{ run: AiSelfcheckRun }>(`/ai-tasks/selfcheck/${id}`);

// ---- Ops AI chat FAB (admin) ----
export interface AdminAiSession {
  id: number;
  title?: string;
  updated_at?: string;
  [k: string]: unknown;
}
export interface AdminAiMessage {
  id: number;
  role: string;
  content: string;
  sources_json?: { path?: string; title?: string; score?: number }[];
  created_at?: string;
  [k: string]: unknown;
}
export const adminAiStatus = () =>
  adm<{ provider: string; configured: boolean; pending_review: number }>("/ai/status");
export const adminAiListSessions = () => adm<{ sessions: AdminAiSession[] }>("/ai/sessions");
export const adminAiCreateSession = (title = "Чат") =>
  adm<AdminAiSession>("/ai/sessions", { method: "POST", body: { title } });
export const adminAiGetMessages = (sessionId: number) =>
  adm<{ session: AdminAiSession; messages: AdminAiMessage[] }>(`/ai/sessions/${sessionId}/messages`);
export const adminAiSendMessage = (
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
    return adm<{
      user: AdminAiMessage;
      assistant: AdminAiMessage;
      sources: unknown[];
      escalated_task?: { id: number; title?: string; status?: string };
    }>(`/ai/sessions/${sessionId}/messages`, { method: "POST", body: fd });
  }
  return adm<{
    user: AdminAiMessage;
    assistant: AdminAiMessage;
    sources: unknown[];
    escalated_task?: { id: number; title?: string; status?: string };
  }>(`/ai/sessions/${sessionId}/messages`, {
    method: "POST",
    body: { content, ...(ui_context ? { ui_context } : {}) },
  });
};
export const adminAiMarkUseful = (sessionId: number, messageId: number, note?: string) =>
  adm<unknown>(`/ai/sessions/${sessionId}/messages/${messageId}/useful`, { method: "POST", body: { note } });
export const adminAiCreateTask = (body: {
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
}) => adm<AdminAiTask>("/ai/tasks", { method: "POST", body });

export type AdminAiPrivacy = {
  consent_required_version: string;
  has_valid_consent: boolean;
  consent?: Record<string, unknown> | null;
  allow_images?: boolean;
  audit_ttl_days?: number;
};
export const adminAiPrivacy = () => adm<AdminAiPrivacy>("/ai/privacy");
export const adminAiGrantConsent = (scopes: string[] = ["llm"], source = "admin_ui") =>
  adm<Record<string, unknown>>("/ai/consent", { method: "POST", body: { scopes, source } });

// ---- Sticker AI (isolated; mutations gated by STICKER_AI_MUTATIONS_ENABLED) ----
export type StickerAiHealth = {
  enabled?: boolean;
  provider?: string;
  provider_ready?: boolean;
  image_model?: string;
  tenant_id?: string;
  queues?: string[];
  queue_snapshot?: Record<string, unknown> | null;
  storage_prefix?: string;
  mutations?: boolean;
  ops_ai_isolated?: boolean;
  observation_reasons?: string[];
  my_permissions?: string[];
  secrets_exposed?: boolean;
  [k: string]: unknown;
};
export type StickerAiTask = {
  id: string;
  status?: string;
  idea_redacted?: string;
  owner_id?: number;
  updated_at?: string;
  variants?: Array<Record<string, unknown>>;
  last_job_id?: string | null;
  [k: string]: unknown;
};
export const stickerAiHealth = () => adm<StickerAiHealth>("/sticker-ai/health");
export const stickerAiListTasks = (status = "all", limit = 50) =>
  adm<{ tasks: StickerAiTask[]; total: number }>("/sticker-ai/tasks", { query: { status, limit } });
export const stickerAiGetTask = (id: string) => adm<StickerAiTask>(`/sticker-ai/tasks/${id}`);
export const stickerAiAssetUrl = (taskId: string, assetKey: string) =>
  `/api/admin/sticker-ai/tasks/${encodeURIComponent(taskId)}/asset?key=${encodeURIComponent(assetKey)}`;
export const stickerAiCreateTask = (body: { idea: string; n_variants?: number; idempotency_key?: string }) =>
  adm<StickerAiTask>("/sticker-ai/tasks", { method: "POST", body });
export const stickerAiGenerate = (id: string, idempotency_key?: string) =>
  adm<StickerAiTask>(`/sticker-ai/tasks/${id}/generate`, {
    method: "POST",
    body: idempotency_key ? { idempotency_key } : {},
  });
export const stickerAiEdit = (
  id: string,
  body: { source_asset_key: string; prompt: string; mask_asset_key?: string },
) => adm<StickerAiTask>(`/sticker-ai/tasks/${id}/edit`, { method: "POST", body });
export const stickerAiSubmitReview = (id: string) =>
  adm<StickerAiTask>(`/sticker-ai/tasks/${id}/submit-review`, { method: "POST", body: {} });
export const stickerAiApprove = (id: string) =>
  adm<StickerAiTask>(`/sticker-ai/tasks/${id}/approve`, { method: "POST", body: {} });
export const stickerAiReject = (id: string, reason = "") =>
  adm<StickerAiTask>(`/sticker-ai/tasks/${id}/reject`, { method: "POST", body: { reason } });
export const stickerAiPublish = (id: string) =>
  adm<StickerAiTask>(`/sticker-ai/tasks/${id}/publish`, { method: "POST", body: {} });
export const stickerAiAudit = (limit = 50) =>
  adm<{ events: Record<string, unknown>[]; total: number }>("/sticker-ai/audit", { query: { limit } });
