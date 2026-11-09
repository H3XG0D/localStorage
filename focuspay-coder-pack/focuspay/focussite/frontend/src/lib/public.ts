// Public (unauthenticated) content endpoints: rates, cryptos, reviews, attribution.
import { api, getToken } from "@/lib/api";

export type CryptoId = "btc" | "usdt" | "trx" | "ltc";

export type BuySpreadTier = { min_amount_rub: number; pct: number };

export interface RateEntry {
  market: number;
  buy: number;
  sell: number;
  need?: number | null;
  buy_commission_pct: number;
  sell_commission_pct: number;
  currency: string;
}

export interface PublicTariffs {
  commissions: Array<{
    id: string;
    label: string;
    pct: number;
    mode?: string;
    note?: string;
    tiers?: BuySpreadTier[];
    pct_from?: number;
    pct_to?: number;
  }>;
  buy_spread_auto_tiers?: BuySpreadTier[];
  buy_limits: { label: string; min_fiat: number; max_fiat: number };
  withdraw_limits: Record<string, number>;
  withdraw_terms: Record<string, unknown>;
}

export interface RatesResponse {
  rates: Partial<Record<CryptoId, RateEntry>>;
  public_tariffs: PublicTariffs;
  updated_at: number | null;
  sell_pricing_mode?: "discount" | "markup" | string;
}

export interface CryptoLimits {
  min_crypto: string;
  max_crypto: string;
  min_fiat: number;
  max_fiat: number;
}
export interface CryptoInfo {
  id: CryptoId;
  name: string;
  ticker: string;
  networks: string[];
  limits: CryptoLimits;
}

export interface Review {
  id: number;
  telegram_message_id: number;
  text: string;
  author_name: string;
  published_at: string;
}
export interface ReviewsResponse {
  channel: string;
  channel_url: string;
  reviews: Review[];
}

export const getRates = () => api<RatesResponse>("/public/rates", { scope: null });
export const getCryptos = () => api<{ cryptos: CryptoInfo[] }>("/public/cryptos", { scope: null });
export const getReviews = (limit = 12) => api<ReviewsResponse>("/public/reviews", { scope: null, query: { limit } });

export interface RefInfo {
  code?: string;
  name?: string;
  ref_token: string;
  bonus_percent?: number;
  telegram_url: string;
  web_url: string;
}
export const getRefInfo = (token: string) => api<RefInfo>(`/public/ref/${token}/info`, { scope: null });
export const getInviteInfo = (token: string) => api<RefInfo>(`/public/invite/${token}/info`, { scope: null });

export function trackAttribution(ref_kind: "promo" | "user" | "auto", ref_token: string, fingerprint?: string) {
  return api<{ ok: boolean }>("/public/attribution/track", {
    method: "POST",
    scope: null,
    body: { ref_kind, ref_token, fingerprint },
  });
}

export type CasinoFairnessGame =
  | "baccara"
  | "blackjack"
  | "holdem"
  | "jackpot"
  | "raffle"
  | "fixed_room"
  | "clan_war"
  | "roulette";
export type CasinoFairnessSide = "creator" | "opponent" | "seat1" | "seat2" | "seat3" | "seat4" | "seat5" | "seat6";

export interface CasinoFairnessVerifyRequest {
  game_type: CasinoFairnessGame;
  game_id: string;
  server_seed: string;
  client_seed: string;
  nonce: number;
  commit: string;
  side?: CasinoFairnessSide;
  hand_size?: number;
  expected_cards?: string[];
  total_tickets?: number;
  expected_ticket?: number;
  hmac_message?: string;
  modulus?: number;
  expected_index?: number;
  expected_pocket?: number;
}

export interface CasinoFairnessVerifyResponse {
  success: boolean;
  fair: boolean;
  matches: boolean;
  commit_matches: boolean;
  cards_match: boolean;
  computed_commit: string;
  algorithm: string;
  client_seed: string;
  nonce: number;
  game_id: string;
  game_type: string;
  cards: { creator?: string[]; opponent?: string[]; [side: string]: string[] | undefined };
  winning_ticket?: number | null;
  total_tickets?: number;
  hmac_message?: string;
  modulus?: number;
  expected_index?: number;
  winner_index?: number | null;
  pocket?: number;
  pocket_matches?: boolean;
  color?: "green" | "red" | "black";
  wheel_index?: number;
}

export function verifyCasinoFairness(body: CasinoFairnessVerifyRequest) {
  return api<CasinoFairnessVerifyResponse>("/public/casino/fairness/verify", {
    method: "POST",
    scope: null,
    body,
  });
}

export interface CasinoLobbyGame {
  id: string;
  name: string;
  category: string;
  emoji: string;
  enabled: boolean;
}

export interface CasinoOpenDuel {
  game_id: string;
  game_type: string;
  bet_rub: number;
  opened_at: string;
}

export interface CasinoOpenRoom {
  room_id: string;
  stake_rub: number;
  seat_count: number;
  filled: number;
  opened_at: string;
}

export interface CasinoLobbyResponse {
  min_bet_rub: number;
  max_bet_rub: number;
  commission_percent: number;
  games: CasinoLobbyGame[];
  open_duels: CasinoOpenDuel[];
  open_rooms?: CasinoOpenRoom[];
}

export function getCasinoLobby() {
  return api<CasinoLobbyResponse>("/public/casino/lobby", { scope: null });
}

export interface CasinoDuelCard {
  game_id: string;
  game_type: string;
  bet_rub: number;
  bank_rub: number;
  commission_rub: number;
  net_payout_rub: number;
  opened_at: string;
  band: string;
  status: string;
  opponent_occupied: boolean;
  is_mine: boolean;
  is_joined: boolean;
  creator?: CasinoChatActor | null;
  opponent?: CasinoChatActor | null;
  steps?: CasinoRevealStep[];
  creator_label?: string;
  opponent_label?: string;
  hands?: { creator: string[]; opponent: string[] };
  can_roll?: boolean;
  rolls_needed?: number;
  my_roll_count?: number;
  roll_deadline_at?: string | null;
  house_will_roll?: boolean;
}

export interface CasinoRevealStep {
  seat: "creator" | "opponent" | string;
  value: number | null;
  index: number;
  creator_sum: number;
  opponent_sum: number;
  leader: "creator" | "opponent" | null;
  card?: string | null;
}

export interface CasinoDuelGroup {
  band: string;
  label: string;
  duels: CasinoDuelCard[];
  open_count: number;
  eta_seconds: number;
  oldest_wait_seconds: number | null;
  fill_label: string;
}

export interface CasinoDuelsResponse {
  commission_percent: number;
  min_bet_rub: number;
  max_bet_rub: number;
  groups: CasinoDuelGroup[];
}

export function getCasinoDuels() {
  return api<CasinoDuelsResponse>("/public/casino/duels");
}

export function getCasinoDuelRoom(gameId: string) {
  return api<CasinoDuelCard>(`/public/casino/duels/${encodeURIComponent(gameId)}`);
}

export function createCasinoDuel(body: { game_type: string; stake_rub: number; autojoin: boolean }) {
  return api<{ success: boolean; joined: boolean; created: boolean; game_id: string; duel: CasinoDuelCard }>(
    "/user/casino/duels",
    { method: "POST", body },
  );
}

export type CasinoRouletteBet = string;

export interface CasinoPlayQuote {
  game_type: string;
  enabled: boolean;
  stake_rub: number;
  min_bet_rub: number;
  max_bet_rub: number;
  payout_multiplier: number;
  win_probability: number | null;
  commission_percent: number;
  gross_payout_rub: number;
  commission_rub: number;
  win_on_win_rub: number;
  bound_error: string | null;
  /** Roulette only: the bet the quote was priced for and its odds table. */
  bet?: CasinoRouletteBet;
  odds_ru?: string;
  profit_ratio?: number;
  bets?: Array<{
    key: string;
    title_ru: string;
    odds_ru: string;
    payout_multiplier: number;
    profit_ratio: number;
    win_probability: number;
    pockets: number[];
  }>;
}

export function getCasinoPlayQuote(
  stakeRub: number,
  gameType = "cub",
  houseBotCount?: number,
  rouletteBet?: CasinoRouletteBet,
) {
  return api<CasinoPlayQuote>("/public/casino/play/quote", {
    query: {
      game_type: gameType,
      stake_rub: stakeRub,
      ...(houseBotCount != null && houseBotCount >= 2 ? { house_bot_count: houseBotCount } : {}),
      ...(rouletteBet ? { bet: rouletteBet } : {}),
    },
  });
}

export interface CasinoTapeRow {
  game_id: string;
  game_type: string;
  stake_rub: number;
  payout_rub: number;
  won: boolean;
  is_mine: boolean;
  player_label: string;
  finished_at: string;
  /** Roulette only: the pocket that came up, for the wheel history. */
  result?: { pocket: number; color: "green" | "red" | "black"; bet: string };
}

export function getCasinoPlayTape(tab: "mine" | "all" | "high", gameType = "cub") {
  return api<{ tab: string; rows: CasinoTapeRow[] }>("/public/casino/play/tape", {
    query: { tab, game_type: gameType },
  });
}

export interface CasinoPlayResult {
  success: boolean;
  game_id: string;
  game_type?: string;
  phase?: "player_turn" | "finished";
  actions?: Array<"hit" | "stand" | string>;
  idempotent?: boolean;
  outcome: {
    kind?: string;
    winner_id?: number | null;
    pocket?: number;
    color?: "green" | "red" | "black";
    bet?: CasinoRouletteBet;
    wheel_index?: number;
  };
  stake_rub: string | number;
  commission_rub: string | number;
  payout_rub: string | number;
  player_pips?: number;
  house_pips?: number;
  player_cards?: string[];
  house_cards?: string[];
  house_up?: string;
  house_hidden?: number;
  player_score?: number;
  house_score?: number;
  /** Roulette only. */
  pocket?: number;
  color?: "green" | "red" | "black";
  wheel_index?: number;
  bet?: CasinoRouletteBet;
  won?: boolean;
  payout_multiplier?: string | number;
  rng?: {
    commit?: string;
    seed?: string;
    nonce?: number;
    message?: string;
    won?: boolean;
    player_pips?: number;
    house_pips?: number;
    player_cards?: string[];
    house_cards?: string[];
    player_score?: number;
    house_score?: number;
    result?: string;
    algorithm?: string;
    client_seed?: string;
    pocket?: number;
    color?: string;
    wheel_index?: number;
    modulus?: number;
  };
  quote?: CasinoPlayQuote;
}

export function playCasinoHouseRound(stakeRub: number, gameType = "cub", rouletteBet?: CasinoRouletteBet) {
  return api<CasinoPlayResult>("/user/casino/play", {
    method: "POST",
    body: { game_type: gameType, stake_rub: stakeRub, ...(rouletteBet ? { bet: rouletteBet } : {}) },
  });
}

export function getCasinoBlackjackPending() {
  return api<{ success: boolean; game_type: string; pending: CasinoPlayResult | null }>(
    "/user/casino/play/pending",
    { query: { game_type: "blackjack" } },
  );
}

export function playCasinoBlackjackAction(gameId: string, action: "hit" | "stand") {
  return api<CasinoPlayResult>("/user/casino/play/action", {
    method: "POST",
    body: { game_id: gameId, action },
  });
}

export interface CasinoHouseTableCard {
  table_id: string;
  game_type: string;
  status: string;
  max_seats: number;
  house_bot_count: number;
  human_count: number;
  free_seats: number;
  state_version: number;
  seats?: CasinoHouseSeat[];
}

export interface CasinoHouseSeat {
  seat_no: number;
  kind: "player" | "house_robot";
  telegram_id: number | null;
  is_self: boolean;
  display_name: string;
  actor?: { user_id: number; display_name: string; initial: string; avatar_url?: string | null } | null;
  stake_rub: number;
  payout_rub: number | null;
  won: boolean | null;
  player_pips: number | null;
  house_pips: number | null;
  status: string;
}

export interface CasinoHouseDie {
  seat_no: number;
  kind: string;
  label: string;
  pips: number | null;
  stake_rub: number;
}

export interface CasinoHouseTableChoice {
  wins: number;
  ties: number;
  win_seats?: number[];
  tie_seats?: number[];
  take_multiplier: number;
  take_payout_rub: number;
  reroll_multiplier: number;
  reroll_payout_rub: number;
  can_reroll: boolean;
  player_pips?: number;
}

export interface CasinoHouseTableSnapshot {
  success: boolean;
  table_id: string;
  game_type: string;
  status: string;
  max_seats: number;
  house_bot_count: number;
  solo?: boolean;
  state_version: number;
  is_seated: boolean;
  can_start: boolean;
  viewer_seat_no: number | null;
  seats: CasinoHouseSeat[];
  dice: { players: CasinoHouseDie[]; house: CasinoHouseDie[] };
  last_round: {
    money?: string;
    shared_pot?: boolean;
    faces?: boolean;
    kind?: string;
    payout_multiplier?: number;
    seats?: Array<{ payout_rub?: number }>;
  };
  choice?: CasinoHouseTableChoice | null;
  money: string;
}

export function getCasinoHouseTables() {
  return casinoAuthedGet<{ tables: CasinoHouseTableCard[] }>(
    "/user/casino/house-tables",
    "/public/casino/house-tables",
  );
}

export function getCasinoHouseTable(tableId: string) {
  const id = encodeURIComponent(tableId);
  return casinoAuthedGet<CasinoHouseTableSnapshot>(
    `/user/casino/house-tables/${id}`,
    `/public/casino/house-tables/${id}`,
  );
}

export function createCasinoHouseTable(body: { stake_rub: number; max_seats?: number; house_bot_count: number }) {
  return api<CasinoHouseTableSnapshot>("/user/casino/house-tables", {
    method: "POST",
    body: { max_seats: 1, ...body },
  });
}

export function sitCasinoHouseTable(tableId: string, body: { stake_rub: number; seat_no?: number }) {
  return api<CasinoHouseTableSnapshot>(`/user/casino/house-tables/${encodeURIComponent(tableId)}/sit`, {
    method: "POST",
    body,
  });
}

export function leaveCasinoHouseTable(tableId: string) {
  return api<CasinoHouseTableSnapshot>(`/user/casino/house-tables/${encodeURIComponent(tableId)}/leave`, {
    method: "POST",
  });
}

export function startCasinoHouseTable(tableId: string) {
  return api<CasinoHouseTableSnapshot>(`/user/casino/house-tables/${encodeURIComponent(tableId)}/start`, {
    method: "POST",
  });
}

export function resolveCasinoHouseTable(tableId: string, action: "take" | "reroll") {
  return api<CasinoHouseTableSnapshot>(`/user/casino/house-tables/${encodeURIComponent(tableId)}/resolve`, {
    method: "POST",
    body: { action },
  });
}

export interface CasinoFairnessSession {
  success: boolean;
  commit_hash: string;
  client_seed: string;
  nonce: number;
  previous_server_seed: string | null;
  previous_commit: string | null;
  rotation_allowed: boolean;
}

export function getCasinoFairnessSession() {
  return api<CasinoFairnessSession>("/user/casino/fairness/session");
}

export function setCasinoFairnessClientSeed(client_seed: string) {
  return api<CasinoFairnessSession>("/user/casino/fairness/client-seed", { method: "POST", body: { client_seed } });
}

export function rotateCasinoFairnessSession() {
  return api<CasinoFairnessSession>("/user/casino/fairness/rotate", { method: "POST" });
}

export interface CasinoPokerLobbyTable {
  table_id: string;
  max_seats: number;
  seated: number;
  small_blind_rub: number;
  big_blind_rub: number;
  min_buyin_rub: number;
  max_buyin_rub: number;
  status: string;
  opened_at: string;
}

export interface CasinoPokerLobby {
  enabled: boolean;
  small_blind_rub: number;
  big_blind_rub: number;
  min_buyin_rub: number;
  max_buyin_rub: number;
  rake_percent: number;
  timeout_seconds: number;
  tables: CasinoPokerLobbyTable[];
}

export interface CasinoPokerSeatView {
  seat_no: number;
  occupied: boolean;
  is_you: boolean;
  stack_rub: number;
  status: string;
  label: string;
  hole?: string[] | null;
  folded?: boolean;
  all_in?: boolean;
  street_bet_rub?: number;
}

export interface CasinoPokerSnapshot {
  success: boolean;
  table_id: string;
  status: string;
  max_seats: number;
  small_blind_rub: number;
  big_blind_rub: number;
  min_buyin_rub: number;
  max_buyin_rub: number;
  rake_percent: number;
  rake_cap_rub: number;
  timeout_seconds: number;
  button_seat: number | null;
  escrow_rub: number;
  state_version: number;
  seats: CasinoPokerSeatView[];
  you_seat: number | null;
  hand: {
    street: string;
    to_act: number | null;
    pot_rub: number;
    board: string[];
    seats: Array<{
      seat_no: number;
      stack_rub: number;
      street_bet_rub: number;
      folded: boolean;
      all_in: boolean;
      hole: string[] | null;
    }>;
    legal: { actions: string[]; call_rub: number; min_raise_to: number; max_raise_to: number };
    winners?: Array<{ seat_no: number; amount: string; reason: string; hand?: string }>;
    action_deadline_at?: string;
    version: number;
  } | null;
  fairness: {
    game_type: string;
    hand_id: string;
    commit: string;
    client_seed: string;
    nonce: number;
    server_seed: string | null;
    board: string[] | null;
  } | null;
  legal: { actions: string[]; call_rub?: number; min_raise_to?: number; max_raise_to?: number };
}

export interface NardyPoint {
  point: number;
  white: number;
  black: number;
}

export interface NardySnapshot {
  table_id: string;
  status: "waiting" | "running" | "done" | "closed";
  stake_rub: number;
  lock_rub: number;
  rake_percent: number;
  state_version: number;
  your_side: "white" | "black" | null;
  white_seated: boolean;
  black_seated: boolean;
  commit: string;
  client_seed: string;
  server_seed: string | null;
  turn: "white" | "black" | null;
  dice: number[] | null;
  start_white: number | null;
  start_black: number | null;
  legal: { index: number; label: string }[];
  points: NardyPoint[];
  white_off: number;
  black_off: number;
  result: { winner: "white" | "black"; kind: "oin" | "mars"; you_won: boolean } | null;
  deadline_at: string | null;
}

export interface NardyLobby {
  enabled: boolean;
  min_stake_rub: number;
  max_stake_rub: number;
  rake_percent: number;
  tables: { table_id: string; stake_rub: number; status: string; seated: number }[];
}

export interface DraughtsPiece {
  square: string;
  side: "white" | "black";
  kind: "man" | "king";
}

export interface DraughtsMove {
  notation: string;
  origin: string;
  path: string[];
  destination: string;
}

export interface DraughtsSnapshot {
  table_id: string;
  status: "waiting" | "running" | "done" | "closed";
  enabled: boolean;
  stake_rub: number;
  min_stake_rub: number;
  max_stake_rub: number;
  rake_percent: number;
  rake_cap_rub: number;
  rake_rub: number;
  state_version: number;
  your_side: "white" | "black" | null;
  your_turn: boolean;
  turn: "white" | "black" | null;
  white_seated: boolean;
  black_seated: boolean;
  pieces: DraughtsPiece[];
  legal_moves: DraughtsMove[];
  moves: string[];
  can_offer_draw: boolean;
  draw_offer: boolean;
  result: "white" | "black" | "draw" | null;
  reason: string;
  your_payout_rub: number | null;
  deadline_at: string | null;
  timeout_seconds: number;
}

export interface DraughtsLobby {
  enabled: boolean;
  min_stake_rub: number;
  max_stake_rub: number;
  rake_percent: number;
  rake_cap_rub: number;
  timeout_seconds: number;
  tables: { table_id: string; stake_rub: number; status: string; seated: number }[];
}

export function getDraughtsLobby() {
  return api<DraughtsLobby>("/public/casino/draughts/tables", { scope: null });
}

export function createDraughtsTable(stake_rub: number) {
  return api<DraughtsSnapshot>("/user/casino/draughts/tables", { method: "POST", body: { stake_rub } });
}

export function getDraughtsTable(tableId: string) {
  return api<DraughtsSnapshot>(`/user/casino/draughts/tables/${encodeURIComponent(tableId)}`);
}

export function joinDraughtsTable(tableId: string) {
  return api<DraughtsSnapshot>(`/user/casino/draughts/tables/${encodeURIComponent(tableId)}/join`, { method: "POST" });
}

export function leaveDraughtsTable(tableId: string) {
  return api<DraughtsSnapshot>(`/user/casino/draughts/tables/${encodeURIComponent(tableId)}/leave`, { method: "POST" });
}

export function actDraughtsTable(tableId: string, body: { notation: string; expected_version: number }) {
  return api<DraughtsSnapshot>(`/user/casino/draughts/tables/${encodeURIComponent(tableId)}/act`, {
    method: "POST",
    body,
  });
}

export function offerDraughtsDraw(tableId: string) {
  return api<DraughtsSnapshot>(`/user/casino/draughts/tables/${encodeURIComponent(tableId)}/draw`, { method: "POST" });
}

export function answerDraughtsDraw(tableId: string, accept: boolean) {
  return api<DraughtsSnapshot>(`/user/casino/draughts/tables/${encodeURIComponent(tableId)}/draw-answer`, {
    method: "POST",
    body: { accept },
  });
}

export function getNardyLobby() {
  return api<NardyLobby>("/public/casino/nardy/tables", { scope: null });
}

export function createNardyTable(stake_rub: number) {
  return api<NardySnapshot>("/user/casino/nardy/tables", { method: "POST", body: { stake_rub } });
}

export function getNardyTable(tableId: string) {
  return api<NardySnapshot>(`/user/casino/nardy/tables/${encodeURIComponent(tableId)}`);
}

export function getNardyWatch(tableId: string) {
  return api<NardySnapshot>(`/public/casino/nardy/tables/${encodeURIComponent(tableId)}`, { scope: null });
}

export function joinNardyTable(tableId: string) {
  return api<NardySnapshot>(`/user/casino/nardy/tables/${encodeURIComponent(tableId)}/join`, { method: "POST" });
}

export function leaveNardyTable(tableId: string) {
  return api<NardySnapshot>(`/user/casino/nardy/tables/${encodeURIComponent(tableId)}/leave`, { method: "POST" });
}

export function actNardyTable(tableId: string, body: { move_index: number; expected_version: number }) {
  return api<NardySnapshot>(`/user/casino/nardy/tables/${encodeURIComponent(tableId)}/act`, { method: "POST", body });
}

export function getCasinoPokerLobby() {
  return api<CasinoPokerLobby>("/public/casino/poker/tables", { scope: null });
}

export function createCasinoPokerTable(max_seats = 6) {
  return api<CasinoPokerSnapshot>("/user/casino/poker/tables", { method: "POST", body: { max_seats } });
}

export function getCasinoPokerTable(tableId: string) {
  return api<CasinoPokerSnapshot>(`/user/casino/poker/tables/${encodeURIComponent(tableId)}`);
}

export function sitCasinoPoker(tableId: string, seat_no: number, buy_in_rub: number) {
  return api<CasinoPokerSnapshot>(`/user/casino/poker/tables/${encodeURIComponent(tableId)}/sit`, {
    method: "POST",
    body: { seat_no, buy_in_rub },
  });
}

export function leaveCasinoPoker(tableId: string) {
  return api<CasinoPokerSnapshot>(`/user/casino/poker/tables/${encodeURIComponent(tableId)}/leave`, {
    method: "POST",
  });
}

export function actCasinoPoker(
  tableId: string,
  body: { action: string; amount_rub?: number | null; expected_version: number },
) {
  return api<CasinoPokerSnapshot>(`/user/casino/poker/tables/${encodeURIComponent(tableId)}/act`, {
    method: "POST",
    body,
  });
}

export function joinCasinoDuel(gameId: string) {
  return api<{ success: boolean; game_id: string; duel: CasinoDuelCard }>(
    `/user/casino/duels/${encodeURIComponent(gameId)}/join`,
    { method: "POST" },
  );
}

export function cancelCasinoDuel(gameId: string) {
  return api<{ success: boolean; cancelled: boolean; game_id: string; duel: CasinoDuelCard }>(
    `/user/casino/duels/${encodeURIComponent(gameId)}/cancel`,
    { method: "POST" },
  );
}

export function rollCasinoDuel(gameId: string) {
  return api<{ success: boolean; game_id: string; duel: CasinoDuelCard }>(
    `/user/casino/duels/${encodeURIComponent(gameId)}/roll`,
    { method: "POST" },
  );
}

export interface CasinoV2Seat {
  seat_no: number;
  participant_kind: "player" | "bot";
  actor: CasinoChatActor;
  is_you: boolean;
  pips: number | null;
  total: number | null;
  rolled: number;
  cards?: string[];
  score?: number | null;
  is_winner?: boolean;
  is_leader?: boolean;
  payout_rub?: string | null;
}

export interface CasinoV2TableView {
  table_id: string;
  game_type: string;
  stake_rub: string;
  max_seats: number;
  status: string;
  state_version: number;
  bot_count: number;
  free_seats: number[];
  roster: CasinoV2Seat[];
  rolls_needed: number;
  my_seat_no: number | null;
  can_roll: boolean;
  can_start: boolean;
  can_add_bot?: boolean;
  can_leave: boolean;
  can_cancel: boolean;
  can_choose_draw?: boolean;
  can_hit?: boolean;
  can_stand?: boolean;
  is_seated: boolean;
  is_creator: boolean;
  roll_deadline_at: string | null;
  countdown_ends_at?: string | null;
  house_will_roll: boolean;
  pot_rub: string;
  commission_rub: string;
  net_payout_rub: string;
  game_state: {
    commit?: string;
    seed?: string;
    rolls?: Record<string, number>;
    phase?: string;
    hands?: Record<string, string[]>;
    scores?: Record<string, number>;
    tie_break_seat_nos?: number[];
    draw_choice_deadline_at?: string;
    cards_dealt_at?: string;
  };
  outcome?: { kind?: string; winner_seat_nos?: number[] };
  settlement?: {
    outcome_kind?: string;
    winner_seat_nos?: number[];
    pot_rub?: string;
    commission_rub?: string;
    payouts?: Array<{ seat_no: number; amount_rub: string }>;
  };
}

export function getCasinoV2Tables(gameType = "pvp_dice") {
  return api<{ success: boolean; tables: CasinoV2TableView[] }>("/public/casino/v2/tables", {
    query: { game_type: gameType },
  });
}

export function getCasinoV2Table(tableId: string) {
  return api<CasinoV2TableView>(`/public/casino/v2/tables/${encodeURIComponent(tableId)}`);
}

export function createCasinoV2Table(body: {
  game_type: string;
  stake_rub: number;
  max_seats: number;
  bot_count: number;
  autojoin: boolean;
}) {
  return api<{ success: boolean; joined: boolean; created: boolean; table_id: string; table: CasinoV2TableView }>(
    "/user/casino/v2/tables",
    { method: "POST", body },
  );
}

function v2VersionBody(tableId: string, expected_state_version: number, path: string) {
  return api<{ success: boolean; table_id: string; table: CasinoV2TableView }>(
    `/user/casino/v2/tables/${encodeURIComponent(tableId)}/${path}`,
    { method: "POST", body: { expected_state_version } },
  );
}

export function joinCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "join");
}

export function addCasinoV2Bot(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "bots");
}

export function startCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "start");
}

export function leaveCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "leave");
}

export function cancelCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "cancel");
}

export function rollCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "roll");
}

export function hitCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "hit");
}

export function standCasinoV2Table(tableId: string, expected_state_version: number) {
  return v2VersionBody(tableId, expected_state_version, "stand");
}

export function chooseCasinoV2Draw(
  tableId: string,
  expected_state_version: number,
  choice: "tie_split" | "redeal",
) {
  return api<{ success: boolean; table_id: string; table: CasinoV2TableView; choice: string }>(
    `/user/casino/v2/tables/${encodeURIComponent(tableId)}/draw-choice`,
    { method: "POST", body: { expected_state_version, choice } },
  );
}

export interface CasinoChatActor {
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url?: string | null;
}

export interface CasinoChatMessage {
  id: number;
  room_id: number;
  kind: "text" | "challenge" | "system" | string;
  body: string;
  payload: Record<string, unknown>;
  created_at: string;
  author: CasinoChatActor;
}

export interface CasinoChatLobby {
  success: boolean;
  room_id: number;
  messages: CasinoChatMessage[];
  online: CasinoChatActor[];
}

export interface CasinoChatThread {
  room_id: number;
  peer: CasinoChatActor;
  last_body: string;
  last_kind: string;
  last_at: string;
}

export function getCasinoChatLobby(before_id = 0) {
  return api<CasinoChatLobby>("/user/casino/chat/lobby", { query: before_id ? { before_id } : {} });
}

export function postCasinoChatLobby(body: string) {
  return api<{ success: boolean; message: CasinoChatMessage }>("/user/casino/chat/lobby", {
    method: "POST",
    body: { body },
  });
}

export function getCasinoChatDms() {
  return api<{ success: boolean; dms: CasinoChatThread[] }>("/user/casino/chat/dms");
}

export function getCasinoChatDm(peerId: number, before_id = 0) {
  return api<{ success: boolean; room_id: number; peer_id: number; messages: CasinoChatMessage[] }>(
    `/user/casino/chat/dms/${peerId}`,
    { query: before_id ? { before_id } : {} },
  );
}

export function postCasinoChatDm(peerId: number, body: string) {
  return api<{ success: boolean; message: CasinoChatMessage }>(`/user/casino/chat/dms/${peerId}`, {
    method: "POST",
    body: { body },
  });
}

export function postCasinoChatChallenge(body: {
  peer_id: number;
  game_type: string;
  stake_rub: number;
  in_lobby?: boolean;
}) {
  return api<{ success: boolean; game_id: string; message: CasinoChatMessage }>("/user/casino/chat/challenge", {
    method: "POST",
    body,
  });
}

export interface CasinoJackpotPlayer {
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url?: string | null;
  amount_rub: number;
  chance_pct: number;
  ticket_from: number;
  ticket_to: number;
}

export interface CasinoJackpotSnapshot {
  success: boolean;
  round_id: string;
  status: string;
  commit_hash: string;
  roll: string | null;
  closes_at: string | null;
  pot_rub: number;
  rake_percent: number;
  rake_rub: number | null;
  payout_rub: number | null;
  winner_id: number | null;
  winning_ticket: number | null;
  player_count: number;
  max_players: number;
  collect_seconds: number;
  min_bet_rub: number;
  max_bet_rub: number;
  enabled: boolean;
  players: CasinoJackpotPlayer[];
  total_tickets: number;
  my_amount_rub: number;
  my_chance_pct: number;
}

export function getCasinoJackpot() {
  return api<CasinoJackpotSnapshot>("/user/casino/jackpot");
}

export function postCasinoJackpotBet(amount_rub: number) {
  return api<CasinoJackpotSnapshot>("/user/casino/jackpot/bet", {
    method: "POST",
    body: { amount_rub },
  });
}

export interface CasinoRafflePlayer {
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url?: string | null;
  tickets: number;
  chance_pct: number;
}

export interface CasinoRaffleWinner extends CasinoRafflePlayer {
  place: number;
  username?: string | null;
  winning_ticket_no: number;
  prize_rub: number;
  payout_status: string;
  eligible_tickets: number;
  tickets: number;
  chance_pct: number;
  hmac_index: number | null;
}

export interface CasinoRaffleSnapshot {
  success: boolean;
  campaign_id: number | null;
  status: string;
  title: string;
  month_label?: string | null;
  kind?: string | null;
  month_key?: string | null;
  commit_hash: string | null;
  server_seed: string | null;
  algorithm: string;
  watch_path: string;
  prize_places: Array<{ place: number; prize_rub: number; payout_method: string }>;
  prize_pool_rub: number;
  spin_interval_seconds: number;
  pre_show_seconds: number;
  next_spin_at: string | null;
  spin_started_at: string | null;
  show_started_at: string | null;
  current_place: number | null;
  next_place: number | null;
  next_prize_rub: number | null;
  remaining_tickets: number;
  player_count: number;
  players: CasinoRafflePlayer[];
  winners: CasinoRaffleWinner[];
  last_winner: CasinoRaffleWinner | null;
  my_user_id: number | null;
  my_tickets: number;
  my_chance_pct: number;
  draw_at: string | null;
}

export interface CasinoRaffleCampaign {
  campaign_id: number;
  title: string;
  month_label?: string | null;
  kind?: string | null;
  month_key?: string | null;
  status: string;
  draw_at: string | null;
  ends_at: string | null;
  prize_pool_rub: number;
  place_count: number;
  winner_count: number;
  ticket_count: number;
  my_tickets: number;
}

export function getCasinoRaffle(campaignId?: number | null) {
  const qs = campaignId ? `?campaign_id=${campaignId}` : "";
  return api<CasinoRaffleSnapshot>(`/user/casino/raffle${qs}`);
}

export function getCasinoRaffleCampaigns() {
  return api<{ campaigns: CasinoRaffleCampaign[] }>("/user/casino/raffle/campaigns");
}

// --- tournaments (several in parallel, each with its own chip wallet) ---

export type CasinoTournamentEntryMode = "free" | "promo" | "paid" | "promo_or_paid";

export interface CasinoTournamentPlayer {
  rank: number;
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url?: string | null;
  chips_balance: number;
  rounds_played: number;
  wins_count: number;
  rebuys_count: number;
  projected_prize_rub: number;
  prize_paid: boolean;
}

export interface CasinoTournamentPrizePlace {
  place: number;
  prize_rub: number;
  leader: CasinoTournamentPlayer | null;
}

export interface CasinoTournamentSnapshot {
  success?: boolean;
  tournament_id: number | null;
  code: string;
  title: string;
  subtitle: string;
  status: string;
  status_label: string;
  starts_at: string | null;
  ends_at: string | null;
  seconds_left: number | null;
  duration_minutes: number;
  entry_mode: CasinoTournamentEntryMode;
  entry_fee_rub: number;
  has_promo: boolean;
  starting_chips: number;
  min_bet_chips: number;
  max_bet_chips: number;
  rebuy_enabled: boolean;
  rebuy_fee_rub: number;
  rebuy_chips: number;
  max_rebuys_per_user: number;
  prize_mode: string;
  prize_pool_rub: number;
  prize_places: CasinoTournamentPrizePlace[];
  require_exchange_history: boolean;
  my_access_granted?: boolean;
  min_rounds_for_prize: number;
  max_participants: number;
  max_bots_per_table: number;
  allowed_games: string[];
  player_count: number;
  players: CasinoTournamentPlayer[];
  me: CasinoTournamentPlayer | null;
  my_user_id: number | null;
  watch_path: string;
}

export interface CasinoTournamentListRow {
  tournament_id: number;
  code: string;
  title: string;
  subtitle: string;
  status: string;
  status_label: string;
  starts_at: string | null;
  ends_at: string | null;
  entry_mode: CasinoTournamentEntryMode;
  entry_fee_rub: number;
  starting_chips: number;
  prize_pool_rub: number;
  player_count: number;
  max_participants: number;
  joined: boolean;
  my_chips: number | null;
}

export interface CasinoTournamentWallet {
  tournament_id: number;
  title: string;
  code: string;
  status: string;
  ends_at: string | null;
  chips_balance: number;
  selected: boolean;
}

export type CasinoWalletKind = "rub" | "bonus" | "tournament";

export interface CasinoWalletRow {
  kind: CasinoWalletKind;
  scope: string;
  title: string;
  unit: "rub" | "chips";
  selected: boolean;
  available_rub?: number;
  chips_balance?: number;
  grant_chips?: number;
  tournament_id?: number | null;
  ends_at?: string | null;
}

export interface CasinoWalletScopeInfo {
  kind: CasinoWalletKind;
  scope: string;
  title: string;
  unit: "rub" | "chips";
  tournament_id: number | null;
}

export interface CasinoWalletsResponse {
  wallets: CasinoWalletRow[];
  active: CasinoWalletScopeInfo;
}

export function getCasinoWallets() {
  return api<CasinoWalletsResponse>("/user/casino/wallets");
}

export function setCasinoWallet(kind: CasinoWalletKind, tournamentId: number | null = null) {
  return api<CasinoWalletsResponse>("/user/casino/wallet", {
    method: "POST",
    body: { kind, tournament_id: tournamentId },
  });
}

export function refillCasinoBonusChips() {
  return api<{ chips_balance: number; granted_chips: number; wallets: CasinoWalletRow[] }>(
    "/user/casino/wallet/bonus/refill",
    { method: "POST" },
  );
}

export function getCasinoTournaments() {
  return api<{ tournaments: CasinoTournamentListRow[] }>("/user/casino/tournaments");
}

export function getCasinoTournament(tournamentId: number) {
  return api<CasinoTournamentSnapshot>(`/user/casino/tournaments/${tournamentId}`);
}

export function getCasinoTournamentWallets() {
  return api<{ wallets: CasinoTournamentWallet[] }>("/user/casino/tournaments/wallets");
}

export function setCasinoTournamentWallet(tournamentId: number | null) {
  return api<{ active_tournament_id: number | null; wallets: CasinoTournamentWallet[] }>(
    "/user/casino/tournaments/wallet",
    { method: "POST", body: { tournament_id: tournamentId } },
  );
}

export function joinCasinoTournament(tournamentId: number, promoCode?: string) {
  return api<CasinoTournamentSnapshot>(`/user/casino/tournaments/${tournamentId}/join`, {
    method: "POST",
    body: { promo_code: promoCode || null },
  });
}

export function rebuyCasinoTournament(tournamentId: number) {
  return api<CasinoTournamentSnapshot>(`/user/casino/tournaments/${tournamentId}/rebuy`, {
    method: "POST",
  });
}

export interface CasinoRouletteTablePlayer {
  id?: number;
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url?: string | null;
  bet: string;
  stake_rub: number;
  pockets: number[];
  odds_ru: string;
  title_ru: string;
}

export interface CasinoRouletteTableHistoryRow {
  id: string;
  pocket: number;
  color: string;
}

export interface CasinoRouletteTableSnapshot {
  success: boolean;
  round_id: string;
  status: string;
  commit_hash: string;
  server_seed: string | null;
  closes_at: string | null;
  pocket: number | null;
  color: string | null;
  wheel_index: number | null;
  player_count: number;
  max_players: number;
  collect_seconds: number;
  min_bet_rub: number;
  max_bet_rub: number;
  max_even_bet_rub?: number;
  max_straight_bet_rub?: number;
  enabled: boolean;
  algorithm: string;
  modulus: number;
  client_seed: string;
  nonce: number;
  hmac_message: string | null;
  players: CasinoRouletteTablePlayer[];
  history: CasinoRouletteTableHistoryRow[];
  my_bet: string | null;
  my_bets?: CasinoRouletteTablePlayer[];
  my_stake_rub: number;
}

export function getCasinoRouletteTable() {
  return api<CasinoRouletteTableSnapshot>("/user/casino/roulette-table");
}

export function getPublicCasinoRouletteTable() {
  return api<CasinoRouletteTableSnapshot>("/public/casino/roulette-table", { scope: null });
}

export function postCasinoRouletteTableBet(amount_rub: number, bet: string) {
  return api<CasinoRouletteTableSnapshot>("/user/casino/roulette-table/bet", {
    method: "POST",
    body: { amount_rub, bet },
  });
}

export function postCasinoRouletteTableBets(chips: Array<{ bet: string; amount_rub: number }>) {
  return api<CasinoRouletteTableSnapshot>("/user/casino/roulette-table/bets", {
    method: "POST",
    body: { chips },
  });
}

export function postCasinoRouletteTableClear(bet?: string) {
  return api<CasinoRouletteTableSnapshot>("/user/casino/roulette-table/clear", {
    method: "POST",
    body: bet ? { bet } : {},
  });
}

export interface CasinoClanMember {
  user_id: number;
  role: string;
  joined_at: string | null;
  display_name: string;
  wager_rub: number;
}

export interface CasinoClan {
  id: number;
  tag: string;
  name: string;
  owner_id: number;
  created_at?: string | null;
  member_count: number;
  max_members: number;
  wager_rub: number;
  week_start: string;
  members?: CasinoClanMember[];
  my_role?: string | null;
  is_owner?: boolean;
  invite_code?: string;
}

export interface CasinoClanTop {
  week_start: string;
  clans: CasinoClan[];
}

export function getCasinoClanTop() {
  return api<CasinoClanTop>("/public/casino/clans/top", { scope: null });
}

export function getCasinoClan(tag: string) {
  return api<CasinoClan>(`/public/casino/clans/${encodeURIComponent(tag)}`, { scope: null });
}

export function getMyCasinoClan() {
  return api<{ clan: CasinoClan | null; enabled: boolean }>("/user/casino/clan");
}

export function postCasinoClanCreate(tag: string, name: string) {
  return api<{ success: boolean; clan: CasinoClan }>("/user/casino/clan", {
    method: "POST",
    body: { tag, name },
  });
}

export function postCasinoClanJoin(code: string) {
  return api<{ success: boolean; clan: CasinoClan }>("/user/casino/clan/join", {
    method: "POST",
    body: { code },
  });
}

export function postCasinoClanLeave() {
  return api<{ ok: boolean; left_tag: string }>("/user/casino/clan/leave", { method: "POST" });
}

export function postCasinoClanKick(user_id: number) {
  return api<{ success: boolean; clan: CasinoClan }>("/user/casino/clan/kick", {
    method: "POST",
    body: { user_id },
  });
}

export function postCasinoClanInvite() {
  return api<{ success: boolean; clan: CasinoClan }>("/user/casino/clan/invite", { method: "POST" });
}

export function postCasinoClanTransfer(user_id: number) {
  return api<{ success: boolean; clan: CasinoClan }>("/user/casino/clan/transfer", {
    method: "POST",
    body: { user_id },
  });
}

export function postCasinoClanDisband() {
  return api<{ ok: boolean; disbanded_tag: string }>("/user/casino/clan/disband", { method: "POST" });
}

export interface CasinoRoomPlayer {
  user_id: number;
  seat_no: number;
  participant_kind?: "player" | "bot";
  display_name: string;
  initial: string;
  avatar_url: string | null;
  amount_rub?: number;
  chance_pct?: number;
}

export interface CasinoRoomSnapshot {
  success?: boolean;
  room_id: string;
  status: string;
  creator_id: number;
  commit_hash: string;
  server_seed: string | null;
  hmac_message: string;
  algorithm: string;
  closes_at: string | null;
  countdown_ends_at?: string | null;
  stake_rub: number;
  seat_count: number;
  filled: number;
  free_seats?: number[];
  pot_rub: number;
  rake_percent: number;
  rake_rub: number | null;
  payout_rub: number | null;
  winner_id: number | null;
  winner_index: number | null;
  players: CasinoRoomPlayer[];
  my_seat: number | null;
  my_amount_rub?: number;
  my_chance_pct?: number;
  can_add_bot?: boolean;
  can_leave?: boolean;
  can_cancel?: boolean;
  min_bet_rub: number;
  max_bet_rub: number;
  max_seats: number;
  collect_seconds: number;
  enabled: boolean;
}

export interface CasinoRoomList {
  success?: boolean;
  enabled: boolean;
  rake_percent: number;
  max_seats: number;
  min_bet_rub: number;
  max_bet_rub: number;
  rooms: CasinoRoomSnapshot[];
}

function casinoAuthedGet<T>(userPath: string, publicPath: string) {
  return getToken() ? api<T>(userPath) : api<T>(publicPath, { scope: null });
}

export function getCasinoRooms() {
  return casinoAuthedGet<CasinoRoomList>("/user/casino/rooms", "/public/casino/rooms");
}

export function getCasinoRoom(roomId: string) {
  const id = encodeURIComponent(roomId);
  return casinoAuthedGet<CasinoRoomSnapshot>(`/user/casino/rooms/${id}`, `/public/casino/rooms/${id}`);
}

export function postCasinoRoom(stake_rub: number, seat_count: number) {
  return api<CasinoRoomSnapshot>("/user/casino/rooms", {
    method: "POST",
    body: { stake_rub, seat_count },
  });
}

export function postCasinoRoomJoin(roomId: string) {
  return api<CasinoRoomSnapshot>(`/user/casino/rooms/${encodeURIComponent(roomId)}/join`, { method: "POST" });
}

export function postCasinoRoomCancel(roomId: string) {
  return api<CasinoRoomSnapshot>(`/user/casino/rooms/${encodeURIComponent(roomId)}/cancel`, { method: "POST" });
}

export function postCasinoRoomLeave(roomId: string) {
  return api<CasinoRoomSnapshot>(`/user/casino/rooms/${encodeURIComponent(roomId)}/leave`, { method: "POST" });
}

export function postCasinoRoomBot(roomId: string) {
  return api<CasinoRoomSnapshot>(`/user/casino/rooms/${encodeURIComponent(roomId)}/bots`, { method: "POST" });
}

export interface CasinoWarFighter {
  user_id: number;
  display_name: string;
  initial: string;
  avatar_url: string | null;
}

export interface CasinoWarSide {
  clan_id: number;
  tag: string;
  name: string;
  fighters: CasinoWarFighter[];
  filled: number;
}

export interface CasinoWarSnapshot {
  success?: boolean;
  war_id: string;
  status: string;
  creator_id: number;
  commit_hash: string;
  server_seed: string | null;
  hmac_message: string | null;
  algorithm: string;
  closes_at: string | null;
  stake_rub: number;
  fighters_needed: number;
  pot_rub: number;
  rake_percent: number;
  rake_rub: number | null;
  payout_per_winner_rub: number | null;
  winner_clan_id: number | null;
  winner_index: number | null;
  challenger: CasinoWarSide | null;
  opponent: CasinoWarSide | null;
  my_side: "challenger" | "opponent" | null;
  min_bet_rub: number;
  max_bet_rub: number;
  max_fighters: number;
  collect_seconds: number;
  enabled: boolean;
  clans_enabled: boolean;
}

export interface CasinoWarList {
  success?: boolean;
  enabled: boolean;
  clans_enabled: boolean;
  rake_percent: number;
  max_fighters: number;
  min_bet_rub: number;
  max_bet_rub: number;
  wars: CasinoWarSnapshot[];
}

export function getCasinoWars() {
  return casinoAuthedGet<CasinoWarList>("/user/casino/wars", "/public/casino/wars");
}

export function getCasinoWar(warId: string) {
  const id = encodeURIComponent(warId);
  return casinoAuthedGet<CasinoWarSnapshot>(`/user/casino/wars/${id}`, `/public/casino/wars/${id}`);
}

export function postCasinoWar(stake_rub: number, fighters_needed: number) {
  return api<CasinoWarSnapshot>("/user/casino/wars", {
    method: "POST",
    body: { stake_rub, fighters_needed },
  });
}

export function postCasinoWarAccept(warId: string) {
  return api<CasinoWarSnapshot>(`/user/casino/wars/${encodeURIComponent(warId)}/accept`, { method: "POST" });
}

export function postCasinoWarJoin(warId: string) {
  return api<CasinoWarSnapshot>(`/user/casino/wars/${encodeURIComponent(warId)}/join`, { method: "POST" });
}

export interface CasinoPlayerLevel {
  index: number;
  min_wager_rub: string;
  cashback_percent: string;
  commission_complete_rate: string;
  commission_active_rate: string;
  reach_bonus_rub?: string;
  remaining_wager_rub?: string;
}

export interface CasinoPlayerProfile {
  success: boolean;
  is_own: boolean;
  player: CasinoChatActor;
  registered_at: string | null;
  week_start: string;
  wager_rub: string;
  lifetime_wager_rub: string;
  wager_by_game: Array<{ game_type: string; label: string; wager_rub: string }>;
  level: CasinoPlayerLevel;
  next_level: CasinoPlayerLevel | null;
  own?: {
    available_rub: string;
    commission_profile: string;
    commission_rate: string;
    cashback_percent: string;
    wagering: Record<string, string>;
    notify_open_tables?: boolean;
    payout_rail?: {
      fiat_deposited_rub?: string;
      card_withdrawn_rub?: string;
      remaining_rub?: string;
      crypto_allowed?: boolean;
    };
  };
}

export function getCasinoPlayer(playerId: number | "me") {
  return api<CasinoPlayerProfile>(`/user/casino/players/${playerId}`);
}

export type CasinoHistoryResult = "win" | "loss" | "push" | "refund";

export interface CasinoHistoryFairness {
  game_type: string;
  game_id: string;
  commit?: string;
  server_seed?: string;
  client_seed?: string;
  nonce?: number;
  side?: string;
  expected_cards?: string;
  total_tickets?: number;
  expected_ticket?: number;
  hmac_message?: string;
  modulus?: number;
  expected_index?: number;
  expected_pocket?: number;
}

export interface CasinoHistoryItem {
  game_type: string;
  label: string;
  round_id: string;
  settled_at: string | null;
  stake_rub: string | null;
  share_percent: string | null;
  result: CasinoHistoryResult;
  result_label: string;
  href: string;
  fairness: CasinoHistoryFairness | null;
  tickets?: number;
}

export interface CasinoPlayerHistory {
  success: boolean;
  items: CasinoHistoryItem[];
  next_before: string | null;
}

export function getCasinoPlayerHistory(
  playerId: number | "me",
  opts?: { before?: string; limit?: number; game_type?: string },
) {
  const query = new URLSearchParams();
  if (opts?.before) query.set("before", opts.before);
  if (opts?.limit != null) query.set("limit", String(opts.limit));
  if (opts?.game_type) query.set("game_type", opts.game_type);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<CasinoPlayerHistory>(`/user/casino/players/${playerId}/history${suffix}`);
}

export interface CasinoHistorySection {
  game_type: string;
  label: string;
  items: CasinoHistoryItem[];
  next_before: string | null;
}

export interface CasinoPlayerHistoryGrouped {
  success: boolean;
  sections: CasinoHistorySection[];
}

export function getCasinoPlayerHistoryGrouped(playerId: number | "me", opts?: { per?: number }) {
  const query = new URLSearchParams();
  if (opts?.per != null) query.set("per", String(opts.per));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<CasinoPlayerHistoryGrouped>(`/user/casino/players/${playerId}/history/grouped${suffix}`);
}

export interface CasinoInboxItem {
  id?: number;
  event_type: string;
  game_id: string;
  href: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
  payload?: { kind?: string; game_type?: string; actor_id?: number };
}

export interface CasinoInboxSession {
  kind: string;
  game_id: string;
  game_type: string;
  href: string;
  title: string;
  body: string;
  status: string;
  stake_rub: string;
  can_cancel?: boolean;
  can_leave?: boolean;
}

export interface CasinoInboxResponse {
  success: boolean;
  unread: number;
  items: CasinoInboxItem[];
  sessions: CasinoInboxSession[];
}

export function getCasinoInbox() {
  return api<CasinoInboxResponse>("/user/casino/inbox");
}

export function readCasinoInbox(ids: number[]) {
  return api<CasinoInboxResponse>("/user/casino/inbox/read", {
    method: "POST",
    body: { ids },
  });
}

export function patchCasinoPlayerLook(nickname: string, extra?: { notify_open_tables?: boolean }) {
  return api<CasinoPlayerProfile>("/user/casino/players/me", {
    method: "PATCH",
    body: extra?.notify_open_tables == null ? { nickname } : { nickname, notify_open_tables: extra.notify_open_tables },
  });
}

export function uploadCasinoPlayerAvatar(file: File) {
  const body = new FormData();
  body.append("file", file);
  return api<CasinoPlayerProfile>("/user/casino/players/me/avatar", { method: "POST", body });
}

export const CRYPTO_META: Record<CryptoId, { label: string; detail: string; networks: string[] }> = {
  usdt: { label: "USDT", detail: "Tether", networks: ["TRC20", "ERC20", "BEP20"] },
  btc: { label: "BTC", detail: "Bitcoin", networks: ["mainnet"] },
  ltc: { label: "LTC", detail: "Litecoin", networks: ["mainnet"] },
  trx: { label: "TRX", detail: "Tron", networks: ["mainnet"] },
};
