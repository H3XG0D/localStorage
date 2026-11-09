export type CasinoClientScope = "operator" | "admin";

export interface CasinoClientPlayer {
  user_id?: number;
  display_name?: string;
  avatar_url?: string | null;
  initial?: string;
  [k: string]: unknown;
}

export interface CasinoClientLevel {
  index?: number;
  min_wager_rub?: string;
  cashback_percent?: string;
  commission_complete_rate?: string;
  commission_active_rate?: string;
  remaining_wager_rub?: string;
  [k: string]: unknown;
}

export interface CasinoClientGame {
  game_type?: string;
  label?: string;
  round_id?: string;
  settled_at?: string | null;
  stake_rub?: string | null;
  result?: string;
  result_label?: string;
  [k: string]: unknown;
}

export interface CasinoClientWithdrawal {
  id?: number;
  amount_rub?: number;
  method?: string;
  crypto?: string;
  status?: string;
  phase?: string;
  status_label?: string;
  status_hint?: string;
  cancellable?: boolean;
  requisites?: string;
  payout_tx_hash?: string | null;
  created_at?: string | null;
  processed_at?: string | null;
  [k: string]: unknown;
}

export interface CasinoClientRisk {
  window?: string;
  rounds?: number;
  wager_rub?: number;
  returned_rub?: number;
  net_rub?: number;
  house_net_rub?: number;
  player_rtp_pct?: number | null;
  game_rtp_pct?: number | null;
  delta_pp?: number | null;
  risk?: string | null;
  [k: string]: unknown;
}

export interface CasinoClientProfile {
  success?: boolean;
  scope?: CasinoClientScope;
  player_id?: number;
  played?: boolean;
  player?: CasinoClientPlayer;
  registered_at?: string | null;
  week_start?: string;
  wager_rub?: string;
  lifetime_wager_rub?: string;
  wager_by_game?: Array<{ game_type?: string; label?: string; wager_rub?: string }>;
  level?: CasinoClientLevel | null;
  next_level?: CasinoClientLevel | null;
  available_rub?: number;
  commission_profile?: string | null;
  commission_rate?: string | null;
  cashback_percent?: string | null;
  wagering?: Record<string, unknown>;
  payout_rail?: Record<string, unknown>;
  raffle?: { campaign_id?: number | null; tickets?: number; status?: string | null };
  recent_games?: CasinoClientGame[];
  history_next_before?: string | null;
  withdrawals?: CasinoClientWithdrawal[];
  risk?: CasinoClientRisk | null;
  [k: string]: unknown;
}

export interface CasinoClientHistoryPage {
  success?: boolean;
  player_id?: number;
  items?: CasinoClientGame[];
  next_before?: string | null;
}
