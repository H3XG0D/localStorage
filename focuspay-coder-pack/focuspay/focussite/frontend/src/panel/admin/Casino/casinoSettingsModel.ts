import type { AdminCasinoGameType, AdminCasinoSettings, AdminCasinoSettingsPatch } from "@/panel/lib/adminApi";
import type { CashbackTierRow, CommissionTierRow, BonusRow } from "@/panel/admin/Casino/CasinoTierGrids";

export const GAME_OPTIONS: ReadonlyArray<{ key: AdminCasinoGameType; label: string }> = [
  { key: "pvp_dice", label: "PVP — кубики" },
  { key: "baccara", label: "Баккара" },
  { key: "blackjack", label: "Блэкджек" },
  { key: "raffle", label: "FocusLucky" },
  { key: "cub", label: "Кубик против казино" },
  { key: "roulette", label: "Рулетка" },
  { key: "holdem", label: "Техасский холдем" },
  { key: "jackpot", label: "Джекпот" },
  { key: "fixed_room", label: "Комнаты" },
  { key: "clan_war", label: "Клан vs клан" },
  { key: "russian_draughts", label: "Русские шашки" },
];

export const SETTINGS_SECTIONS = [
  { id: "commission", title: "Комиссия и доли" },
  { id: "limits", title: "Лимиты" },
  { id: "holdem", title: "Холдем" },
  { id: "draughts", title: "Русские шашки" },
  { id: "jackpot", title: "Джекпот" },
  { id: "roulette_table", title: "Рулетка стол" },
  { id: "clans", title: "Кланы" },
  { id: "fixed_rooms", title: "Комнаты" },
  { id: "clan_wars", title: "Война кланов" },
  { id: "bankroll", title: "Банкролл и защита" },
  { id: "tiers", title: "Уровни" },
  { id: "responsible", title: "Ответственная игра" },
  { id: "payouts", title: "Пороги вывода" },
  { id: "fairness", title: "Честность" },
  { id: "games", title: "Включённые игры" },
  { id: "danger", title: "Опасная зона" },
] as const;

export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]["id"];

export type NumericField =
  | "wagering_percent"
  | "commission_rate_wagering_active"
  | "commission_rate_wagering_complete"
  | "creator_cut_percent_wagering_active"
  | "referral_l1_percent_wagering_active"
  | "referral_l2_percent_wagering_active"
  | "creator_cut_percent_wagering_complete"
  | "referral_l1_percent_wagering_complete"
  | "referral_l2_percent_wagering_complete"
  | "min_bet_rub"
  | "max_bet_rub"
  | "min_withdrawal_rub"
  | "max_profit_pct_per_round"
  | "max_profit_pct_per_round_all"
  | "bankroll_floor_rub"
  | "liability_amount_rub"
  | "bet_step_rub"
  | "max_concurrent_games_per_player"
  | "pending_invite_ttl_minutes"
  | "move_timeout_minutes"
  | "holdem_small_blind_rub"
  | "holdem_big_blind_rub"
  | "holdem_rake_percent"
  | "holdem_rake_cap_rub"
  | "holdem_action_timeout_seconds"
  | "draughts_move_timeout_seconds"
  | "holdem_min_buyin_bb"
  | "holdem_max_buyin_bb"
  | "jackpot_collect_seconds"
  | "jackpot_max_players"
  | "jackpot_rake_percent"
  | "roulette_table_collect_seconds"
  | "roulette_table_max_players"
  | "clan_max_members"
  | "fixed_room_rake_percent"
  | "fixed_room_max_seats"
  | "fixed_room_collect_seconds"
  | "clan_war_rake_percent"
  | "clan_war_max_fighters"
  | "clan_war_collect_seconds"
  | "commission_cap_rub"
  | "commission_min_rub"
  | "reality_check_default_minutes"
  | "self_exclusion_min_hours"
  | "timeout_max_hours"
  | "limit_loosening_delay_hours"
  | "withdrawal_auto_approve_max_rub"
  | "withdrawal_manual_review_min_rub"
  | "withdrawal_daily_limit_rub"
  | "withdrawal_hourly_limit_rub";

export type BoolField =
  | "deposit_limit_enabled"
  | "loss_limit_enabled"
  | "wager_limit_enabled"
  | "session_limit_enabled"
  | "clans_enabled"
  | "seed_rotation_allowed";

type GameBoundForm = Record<AdminCasinoGameType, { min: string; max: string }>;
type GameNumberForm = Record<AdminCasinoGameType, string>;
type GameFlagForm = Record<AdminCasinoGameType, boolean>;

export type SettingsForm = Record<NumericField, string> &
  Record<BoolField, boolean> & {
    enabled_games: GameFlagForm;
    per_game_limits: GameBoundForm;
    max_rounds_per_player_per_day: GameNumberForm;
    provably_fair_enabled: GameFlagForm;
  };

export type SettingsSnapshot = {
  form: SettingsForm;
  cashbackTiers: CashbackTierRow[];
  commissionTiers: CommissionTierRow[];
  bonusRows: BonusRow[];
};

export type FieldError = { id: string; message: string };

function emptyGameFlags(source: Partial<Record<AdminCasinoGameType, boolean>> | undefined, fallback: boolean): GameFlagForm {
  const flags = {} as GameFlagForm;
  for (const game of GAME_OPTIONS) {
    flags[game.key] = source?.[game.key] === true ? true : source?.[game.key] === false ? false : fallback;
  }
  return flags;
}

function toGameBounds(source: AdminCasinoSettings["per_game_limits"] | undefined): GameBoundForm {
  const bounds = {} as GameBoundForm;
  for (const game of GAME_OPTIONS) {
    const row = source?.[game.key];
    bounds[game.key] = {
      min: row?.min != null ? String(row.min) : "",
      max: row?.max != null ? String(row.max) : "",
    };
  }
  return bounds;
}

function toGameNumbers(source: AdminCasinoSettings["max_rounds_per_player_per_day"] | undefined): GameNumberForm {
  const values = {} as GameNumberForm;
  for (const game of GAME_OPTIONS) {
    values[game.key] = source?.[game.key] != null ? String(source[game.key]) : "";
  }
  return values;
}

export function toForm(settings: AdminCasinoSettings): SettingsForm {
  return {
    wagering_percent: String(settings.wagering_percent),
    commission_rate_wagering_active: String(settings.commission_rate_wagering_active),
    commission_rate_wagering_complete: String(settings.commission_rate_wagering_complete),
    creator_cut_percent_wagering_active: String(settings.creator_cut_percent_wagering_active),
    referral_l1_percent_wagering_active: String(settings.referral_l1_percent_wagering_active),
    referral_l2_percent_wagering_active: String(settings.referral_l2_percent_wagering_active),
    creator_cut_percent_wagering_complete: String(settings.creator_cut_percent_wagering_complete),
    referral_l1_percent_wagering_complete: String(settings.referral_l1_percent_wagering_complete),
    referral_l2_percent_wagering_complete: String(settings.referral_l2_percent_wagering_complete),
    min_bet_rub: String(settings.min_bet_rub),
    max_bet_rub: String(settings.max_bet_rub),
    min_withdrawal_rub: String(settings.min_withdrawal_rub),
    max_profit_pct_per_round: String(settings.max_profit_pct_per_round ?? 1),
    max_profit_pct_per_round_all: String(settings.max_profit_pct_per_round_all ?? 1.5),
    bankroll_floor_rub: String(settings.bankroll_floor_rub ?? 0),
    liability_amount_rub: String(settings.liability_amount_rub ?? 0),
    bet_step_rub: String(settings.bet_step_rub ?? 10),
    max_concurrent_games_per_player: String(settings.max_concurrent_games_per_player ?? 10),
    pending_invite_ttl_minutes: String(settings.pending_invite_ttl_minutes ?? 10),
    move_timeout_minutes: String(settings.move_timeout_minutes ?? 120),
    holdem_small_blind_rub: String(settings.holdem_small_blind_rub ?? 10),
    holdem_big_blind_rub: String(settings.holdem_big_blind_rub ?? 20),
    holdem_rake_percent: String(settings.holdem_rake_percent ?? 5),
    holdem_rake_cap_rub: String(settings.holdem_rake_cap_rub ?? 50),
    holdem_action_timeout_seconds: String(settings.holdem_action_timeout_seconds ?? 30),
    draughts_move_timeout_seconds: String(settings.draughts_move_timeout_seconds ?? 30),
    holdem_min_buyin_bb: String(settings.holdem_min_buyin_bb ?? 20),
    holdem_max_buyin_bb: String(settings.holdem_max_buyin_bb ?? 100),
    jackpot_collect_seconds: String(settings.jackpot_collect_seconds ?? 300),
    jackpot_max_players: String(settings.jackpot_max_players ?? 30),
    jackpot_rake_percent: String(settings.jackpot_rake_percent ?? 5),
    roulette_table_collect_seconds: String(settings.roulette_table_collect_seconds ?? 25),
    roulette_table_max_players: String(settings.roulette_table_max_players ?? 24),
    clan_max_members: String(settings.clan_max_members ?? 20),
    fixed_room_rake_percent: String(settings.fixed_room_rake_percent ?? 5),
    fixed_room_max_seats: String(settings.fixed_room_max_seats ?? 10),
    fixed_room_collect_seconds: String(settings.fixed_room_collect_seconds ?? 600),
    clan_war_rake_percent: String(settings.clan_war_rake_percent ?? 5),
    clan_war_max_fighters: String(settings.clan_war_max_fighters ?? 5),
    clan_war_collect_seconds: String(settings.clan_war_collect_seconds ?? 1800),
    commission_cap_rub: String(settings.commission_cap_rub ?? 0),
    commission_min_rub: String(settings.commission_min_rub ?? 0),
    reality_check_default_minutes: String(settings.reality_check_default_minutes ?? 60),
    self_exclusion_min_hours: String(settings.self_exclusion_min_hours ?? 24),
    timeout_max_hours: String(settings.timeout_max_hours ?? 72),
    limit_loosening_delay_hours: String(settings.limit_loosening_delay_hours ?? 24),
    withdrawal_auto_approve_max_rub: String(settings.withdrawal_auto_approve_max_rub ?? 0),
    withdrawal_manual_review_min_rub: String(settings.withdrawal_manual_review_min_rub ?? 0),
    withdrawal_daily_limit_rub: String(settings.withdrawal_daily_limit_rub ?? 0),
    withdrawal_hourly_limit_rub: String(settings.withdrawal_hourly_limit_rub ?? 0),
    deposit_limit_enabled: settings.deposit_limit_enabled === true,
    loss_limit_enabled: settings.loss_limit_enabled === true,
    wager_limit_enabled: settings.wager_limit_enabled === true,
    session_limit_enabled: settings.session_limit_enabled === true,
    clans_enabled: settings.clans_enabled !== false,
    seed_rotation_allowed: settings.seed_rotation_allowed !== false,
    enabled_games: emptyGameFlags(settings.enabled_games, false),
    per_game_limits: toGameBounds(settings.per_game_limits),
    max_rounds_per_player_per_day: toGameNumbers(settings.max_rounds_per_player_per_day),
    provably_fair_enabled: emptyGameFlags(settings.provably_fair_enabled, false),
  };
}

export function cloneSnapshot(
  form: SettingsForm,
  cashbackTiers: CashbackTierRow[],
  commissionTiers: CommissionTierRow[],
  bonusRows: BonusRow[],
): SettingsSnapshot {
  return structuredClone({ form, cashbackTiers, commissionTiers, bonusRows });
}

export function parseRequiredNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function parseRequiredInteger(value: string): number | null {
  const parsed = parseRequiredNumber(value);
  if (parsed == null || !Number.isInteger(parsed)) return null;
  return parsed;
}

function fieldId(field: string): string {
  return `field-${field}`;
}

export function validateForm(form: SettingsForm): { snapshot?: AdminCasinoSettingsPatch; errors: FieldError[] } {
  const errors: FieldError[] = [];
  const push = (id: string, message: string) => errors.push({ id, message });

  const numberField = (field: NumericField, label: string, integer = false): number | null => {
    const parsed = integer ? parseRequiredInteger(form[field]) : parseRequiredNumber(form[field]);
    if (parsed == null) {
      push(fieldId(field), `${label}: укажите ${integer ? "целое число" : "число"}`);
      return null;
    }
    return parsed;
  };

  const wagering = numberField("wagering_percent", "Отыгрыш");
  const activeCommission = numberField("commission_rate_wagering_active", "Комиссия до отыгрыша");
  const completeCommission = numberField("commission_rate_wagering_complete", "Комиссия после отыгрыша");
  const creatorActive = numberField("creator_cut_percent_wagering_active", "Creator до отыгрыша");
  const l1Active = numberField("referral_l1_percent_wagering_active", "Реферал L1 до отыгрыша");
  const l2Active = numberField("referral_l2_percent_wagering_active", "Реферал L2 до отыгрыша");
  const creatorComplete = numberField("creator_cut_percent_wagering_complete", "Creator после отыгрыша");
  const l1Complete = numberField("referral_l1_percent_wagering_complete", "Реферал L1 после отыгрыша");
  const l2Complete = numberField("referral_l2_percent_wagering_complete", "Реферал L2 после отыгрыша");
  const minBet = numberField("min_bet_rub", "Минимальная ставка");
  const maxBet = numberField("max_bet_rub", "Максимальная ставка");
  const minWithdrawal = numberField("min_withdrawal_rub", "Минимальный вывод");
  const maxProfitPct = numberField("max_profit_pct_per_round", "Макс. выигрыш за раунд");
  const maxProfitPctAll = numberField("max_profit_pct_per_round_all", "Макс. выигрыш всех");
  const bankrollFloor = numberField("bankroll_floor_rub", "Порог банкролла");
  const liability = numberField("liability_amount_rub", "Потолок обязательств");
  const betStep = numberField("bet_step_rub", "Шаг ставки");
  const concurrent = numberField("max_concurrent_games_per_player", "Макс. одновременных игр", true);
  const inviteTtl = numberField("pending_invite_ttl_minutes", "TTL приглашения", true);
  const moveTimeout = numberField("move_timeout_minutes", "Таймаут хода", true);
  const holdemSb = numberField("holdem_small_blind_rub", "Малый блайнд");
  const holdemBb = numberField("holdem_big_blind_rub", "Большой блайнд");
  const holdemRake = numberField("holdem_rake_percent", "Рейк холдема");
  const holdemRakeCap = numberField("holdem_rake_cap_rub", "Потолок рейка");
  const holdemTimeout = numberField("holdem_action_timeout_seconds", "Таймаут хода холдема", true);
  const draughtsTimeout = numberField("draughts_move_timeout_seconds", "Таймаут хода шашек", true);
  const holdemMinBb = numberField("holdem_min_buyin_bb", "Мин. бай-ин (BB)", true);
  const holdemMaxBb = numberField("holdem_max_buyin_bb", "Макс. бай-ин (BB)", true);
  const jackpotCollect = numberField("jackpot_collect_seconds", "Джекпот: сбор", true);
  const jackpotMaxPlayers = numberField("jackpot_max_players", "Джекпот: макс. игроков", true);
  const jackpotRake = numberField("jackpot_rake_percent", "Джекпот: рейк");
  const rouletteTableCollect = numberField("roulette_table_collect_seconds", "Рулетка стол: сбор", true);
  const rouletteTableMax = numberField("roulette_table_max_players", "Рулетка стол: макс. игроков", true);
  const clanMax = numberField("clan_max_members", "Кланы: макс. состав", true);
  const fixedRoomRake = numberField("fixed_room_rake_percent", "Комнаты: рейк");
  const fixedRoomSeats = numberField("fixed_room_max_seats", "Комнаты: макс. мест", true);
  const fixedRoomCollect = numberField("fixed_room_collect_seconds", "Комнаты: набор", true);
  const clanWarRake = numberField("clan_war_rake_percent", "Война кланов: рейк");
  const clanWarFighters = numberField("clan_war_max_fighters", "Война кланов: бойцов", true);
  const clanWarCollect = numberField("clan_war_collect_seconds", "Война кланов: набор", true);
  const commissionCap = numberField("commission_cap_rub", "Потолок комиссии");
  const commissionMin = numberField("commission_min_rub", "Минимальная комиссия");
  const realityCheck = numberField("reality_check_default_minutes", "Напоминание", true);
  const selfExclusion = numberField("self_exclusion_min_hours", "Мин. самоисключение", true);
  const timeoutMax = numberField("timeout_max_hours", "Макс. тайм-аут", true);
  const looseningDelay = numberField("limit_loosening_delay_hours", "Задержка ослабления", true);
  const autoApprove = numberField("withdrawal_auto_approve_max_rub", "Автовывод до");
  const manualReview = numberField("withdrawal_manual_review_min_rub", "Ручная проверка от");
  const dailyLimit = numberField("withdrawal_daily_limit_rub", "Дневной лимит вывода");
  const hourlyLimit = numberField("withdrawal_hourly_limit_rub", "Часовой лимит вывода");

  const percents: Array<[number | null, string]> = [
    [wagering, "wagering_percent"],
    [activeCommission, "commission_rate_wagering_active"],
    [completeCommission, "commission_rate_wagering_complete"],
    [creatorActive, "creator_cut_percent_wagering_active"],
    [l1Active, "referral_l1_percent_wagering_active"],
    [l2Active, "referral_l2_percent_wagering_active"],
    [creatorComplete, "creator_cut_percent_wagering_complete"],
    [l1Complete, "referral_l1_percent_wagering_complete"],
    [l2Complete, "referral_l2_percent_wagering_complete"],
    [maxProfitPct, "max_profit_pct_per_round"],
    [maxProfitPctAll, "max_profit_pct_per_round_all"],
    [holdemRake, "holdem_rake_percent"],
    [jackpotRake, "jackpot_rake_percent"],
    [fixedRoomRake, "fixed_room_rake_percent"],
    [clanWarRake, "clan_war_rake_percent"],
  ];
  for (const [value, field] of percents) {
    if (value != null && (value < 0 || value > 100)) {
      push(fieldId(field), "Все проценты должны быть в диапазоне от 0 до 100");
    }
  }

  if (
    activeCommission != null &&
    creatorActive != null &&
    l1Active != null &&
    l2Active != null &&
    creatorActive + l1Active + l2Active > activeCommission
  ) {
    push(fieldId("creator_cut_percent_wagering_active"), "Доли при активном отыгрыше не могут превышать его комиссию");
  }
  if (
    completeCommission != null &&
    creatorComplete != null &&
    l1Complete != null &&
    l2Complete != null &&
    creatorComplete + l1Complete + l2Complete > completeCommission
  ) {
    push(fieldId("creator_cut_percent_wagering_complete"), "Доли после отыгрыша не могут превышать его комиссию");
  }
  if (minBet != null && minBet <= 0) push(fieldId("min_bet_rub"), "Минимальная ставка должна быть больше нуля");
  if (maxBet != null && maxBet <= 0) push(fieldId("max_bet_rub"), "Максимальная ставка должна быть больше нуля");
  if (minWithdrawal != null && minWithdrawal <= 0) {
    push(fieldId("min_withdrawal_rub"), "Минимальная сумма вывода должна быть больше нуля");
  }
  if (minBet != null && maxBet != null && minBet > maxBet) {
    push(fieldId("min_bet_rub"), "Минимальная ставка не может быть больше максимальной");
  }
  if (betStep != null && betStep <= 0) push(fieldId("bet_step_rub"), "Шаг ставки должен быть больше нуля");
  if (concurrent != null && concurrent < 1) {
    push(fieldId("max_concurrent_games_per_player"), "Максимум одновременных игр должен быть не меньше 1");
  }
  if (inviteTtl != null && (inviteTtl < 1 || inviteTtl > 60)) {
    push(fieldId("pending_invite_ttl_minutes"), "TTL приглашения должен быть от 1 до 60 минут");
  }
  if (moveTimeout != null && moveTimeout < 1) push(fieldId("move_timeout_minutes"), "Таймаут хода должен быть не меньше 1");
  if (holdemSb != null && holdemSb <= 0) push(fieldId("holdem_small_blind_rub"), "Малый блайнд должен быть больше нуля");
  if (holdemBb != null && holdemBb <= 0) push(fieldId("holdem_big_blind_rub"), "Большой блайнд должен быть больше нуля");
  if (holdemSb != null && holdemBb != null && holdemSb > holdemBb) {
    push(fieldId("holdem_small_blind_rub"), "Малый блайнд не может быть больше большого");
  }
  if (holdemTimeout != null && (holdemTimeout < 5 || holdemTimeout > 300)) {
    push(fieldId("holdem_action_timeout_seconds"), "Таймаут хода холдема: 5–300 секунд");
  }
  if (draughtsTimeout != null && (draughtsTimeout < 5 || draughtsTimeout > 300)) {
    push(fieldId("draughts_move_timeout_seconds"), "Таймаут хода шашек: 5–300 секунд");
  }
  if (holdemMinBb != null && holdemMinBb < 2) push(fieldId("holdem_min_buyin_bb"), "Мин. бай-ин должен быть не меньше 2 BB");
  if (holdemMaxBb != null && holdemMaxBb < 2) push(fieldId("holdem_max_buyin_bb"), "Макс. бай-ин должен быть не меньше 2 BB");
  if (holdemMinBb != null && holdemMaxBb != null && holdemMinBb > holdemMaxBb) {
    push(fieldId("holdem_min_buyin_bb"), "Мин. бай-ин (BB) не может быть больше максимального");
  }
  if (jackpotCollect != null && (jackpotCollect < 30 || jackpotCollect > 3600)) {
    push(fieldId("jackpot_collect_seconds"), "Сбор джекпота: 30–3600 секунд");
  }
  if (jackpotMaxPlayers != null && (jackpotMaxPlayers < 2 || jackpotMaxPlayers > 100)) {
    push(fieldId("jackpot_max_players"), "Макс. игроков джекпота: 2–100");
  }
  if (rouletteTableCollect != null && (rouletteTableCollect < 5 || rouletteTableCollect > 120)) {
    push(fieldId("roulette_table_collect_seconds"), "Сбор стола рулетки: 5–120 секунд");
  }
  if (rouletteTableMax != null && (rouletteTableMax < 2 || rouletteTableMax > 48)) {
    push(fieldId("roulette_table_max_players"), "Макс. игроков стола рулетки: 2–48");
  }
  if (clanMax != null && (clanMax < 2 || clanMax > 50)) {
    push(fieldId("clan_max_members"), "Макс. состав клана: 2–50");
  }
  if (selfExclusion != null && selfExclusion < 1) {
    push(fieldId("self_exclusion_min_hours"), "Самоисключение должно быть не меньше 1");
  }
  if (timeoutMax != null && timeoutMax < 1) push(fieldId("timeout_max_hours"), "Тайм-аут должен быть не меньше 1");

  const nonNegative: Array<[number | null, string, string]> = [
    [bankrollFloor, "bankroll_floor_rub", "Порог банкролла"],
    [liability, "liability_amount_rub", "Потолок обязательств"],
    [commissionCap, "commission_cap_rub", "Потолок комиссии"],
    [commissionMin, "commission_min_rub", "Минимальная комиссия"],
    [realityCheck, "reality_check_default_minutes", "Напоминание"],
    [looseningDelay, "limit_loosening_delay_hours", "Задержка ослабления"],
    [autoApprove, "withdrawal_auto_approve_max_rub", "Автовывод"],
    [manualReview, "withdrawal_manual_review_min_rub", "Ручная проверка"],
    [dailyLimit, "withdrawal_daily_limit_rub", "Дневной лимит"],
    [hourlyLimit, "withdrawal_hourly_limit_rub", "Часовой лимит"],
    [holdemRakeCap, "holdem_rake_cap_rub", "Потолок рейка"],
  ];
  for (const [value, field, label] of nonNegative) {
    if (value != null && value < 0) push(fieldId(field), `${label} не может быть отрицательным. 0 = выключено`);
  }

  const perGameLimits: NonNullable<AdminCasinoSettingsPatch["per_game_limits"]> = {};
  for (const game of GAME_OPTIONS) {
    const minRaw = form.per_game_limits[game.key].min.trim();
    const maxRaw = form.per_game_limits[game.key].max.trim();
    if (!minRaw && !maxRaw) continue;
    const row: { min?: number; max?: number } = {};
    if (minRaw) {
      const parsed = Number(minRaw);
      if (!Number.isFinite(parsed) || parsed < 0) {
        push(`field-per_game-${game.key}-min`, `Лимит ${game.label}: минимальная ставка должна быть числом ≥ 0`);
      } else row.min = parsed;
    }
    if (maxRaw) {
      const parsed = Number(maxRaw);
      if (!Number.isFinite(parsed) || parsed < 0) {
        push(`field-per_game-${game.key}-max`, `Лимит ${game.label}: максимальная ставка должна быть числом ≥ 0`);
      } else row.max = parsed;
    }
    if (row.min != null && row.max != null && row.min > row.max) {
      push(`field-per_game-${game.key}-min`, `Лимит ${game.label}: min не может быть больше max`);
    }
    if (row.min != null || row.max != null) perGameLimits[game.key] = row;
  }

  const maxRounds: NonNullable<AdminCasinoSettingsPatch["max_rounds_per_player_per_day"]> = {};
  for (const game of GAME_OPTIONS) {
    const raw = form.max_rounds_per_player_per_day[game.key].trim();
    if (!raw) continue;
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < 0) {
      push(`field-rounds-${game.key}`, `Раундов в день (${game.label}): целое число ≥ 0, пусто = без лимита`);
    } else maxRounds[game.key] = parsed;
  }

  if (errors.length) return { errors };

  return {
    errors,
    snapshot: {
      wagering_percent: wagering!,
      commission_rate_wagering_active: activeCommission!,
      commission_rate_wagering_complete: completeCommission!,
      creator_cut_percent_wagering_active: creatorActive!,
      referral_l1_percent_wagering_active: l1Active!,
      referral_l2_percent_wagering_active: l2Active!,
      creator_cut_percent_wagering_complete: creatorComplete!,
      referral_l1_percent_wagering_complete: l1Complete!,
      referral_l2_percent_wagering_complete: l2Complete!,
      min_bet_rub: minBet!,
      max_bet_rub: maxBet!,
      min_withdrawal_rub: minWithdrawal!,
      max_profit_pct_per_round: maxProfitPct!,
      max_profit_pct_per_round_all: maxProfitPctAll!,
      bankroll_floor_rub: bankrollFloor!,
      liability_amount_rub: liability!,
      bet_step_rub: betStep!,
      max_concurrent_games_per_player: concurrent!,
      pending_invite_ttl_minutes: inviteTtl!,
      move_timeout_minutes: moveTimeout!,
      holdem_small_blind_rub: holdemSb!,
      holdem_big_blind_rub: holdemBb!,
      holdem_rake_percent: holdemRake!,
      holdem_rake_cap_rub: holdemRakeCap!,
      holdem_action_timeout_seconds: holdemTimeout!,
      draughts_move_timeout_seconds: draughtsTimeout!,
      holdem_min_buyin_bb: holdemMinBb!,
      holdem_max_buyin_bb: holdemMaxBb!,
      jackpot_collect_seconds: jackpotCollect!,
      jackpot_max_players: jackpotMaxPlayers!,
      jackpot_rake_percent: jackpotRake!,
      roulette_table_collect_seconds: rouletteTableCollect!,
      roulette_table_max_players: rouletteTableMax!,
      clan_max_members: clanMax!,
      clans_enabled: form.clans_enabled,
      fixed_room_rake_percent: fixedRoomRake!,
      fixed_room_max_seats: fixedRoomSeats!,
      fixed_room_collect_seconds: fixedRoomCollect!,
      clan_war_rake_percent: clanWarRake!,
      clan_war_max_fighters: clanWarFighters!,
      clan_war_collect_seconds: clanWarCollect!,
      commission_cap_rub: commissionCap!,
      commission_min_rub: commissionMin!,
      reality_check_default_minutes: realityCheck!,
      self_exclusion_min_hours: selfExclusion!,
      timeout_max_hours: timeoutMax!,
      limit_loosening_delay_hours: looseningDelay!,
      withdrawal_auto_approve_max_rub: autoApprove!,
      withdrawal_manual_review_min_rub: manualReview!,
      withdrawal_daily_limit_rub: dailyLimit!,
      withdrawal_hourly_limit_rub: hourlyLimit!,
      deposit_limit_enabled: form.deposit_limit_enabled,
      loss_limit_enabled: form.loss_limit_enabled,
      wager_limit_enabled: form.wager_limit_enabled,
      session_limit_enabled: form.session_limit_enabled,
      seed_rotation_allowed: form.seed_rotation_allowed,
      enabled_games: { ...form.enabled_games },
      per_game_limits: perGameLimits,
      max_rounds_per_player_per_day: maxRounds,
      provably_fair_enabled: { ...form.provably_fair_enabled },
    },
  };
}

const COMMISSION_FIELDS: NumericField[] = [
  "wagering_percent",
  "commission_rate_wagering_active",
  "commission_rate_wagering_complete",
  "creator_cut_percent_wagering_active",
  "referral_l1_percent_wagering_active",
  "referral_l2_percent_wagering_active",
  "creator_cut_percent_wagering_complete",
  "referral_l1_percent_wagering_complete",
  "referral_l2_percent_wagering_complete",
  "commission_cap_rub",
  "commission_min_rub",
];
const LIMIT_FIELDS: NumericField[] = [
  "min_bet_rub",
  "max_bet_rub",
  "bet_step_rub",
  "max_concurrent_games_per_player",
  "pending_invite_ttl_minutes",
  "move_timeout_minutes",
];
const DRAUGHTS_FIELDS: NumericField[] = ["draughts_move_timeout_seconds"];
const HOLDEM_FIELDS: NumericField[] = [
  "holdem_small_blind_rub",
  "holdem_big_blind_rub",
  "holdem_rake_percent",
  "holdem_rake_cap_rub",
  "holdem_action_timeout_seconds",
  "holdem_min_buyin_bb",
  "holdem_max_buyin_bb",
];
const JACKPOT_FIELDS: NumericField[] = [
  "jackpot_collect_seconds",
  "jackpot_max_players",
  "jackpot_rake_percent",
];
const ROULETTE_TABLE_FIELDS: NumericField[] = [
  "roulette_table_collect_seconds",
  "roulette_table_max_players",
];
const CLAN_FIELDS: NumericField[] = ["clan_max_members"];
const FIXED_ROOM_FIELDS: NumericField[] = [
  "fixed_room_rake_percent",
  "fixed_room_max_seats",
  "fixed_room_collect_seconds",
];
const CLAN_WAR_FIELDS: NumericField[] = [
  "clan_war_rake_percent",
  "clan_war_max_fighters",
  "clan_war_collect_seconds",
];
const BANKROLL_FIELDS: NumericField[] = [
  "max_profit_pct_per_round",
  "max_profit_pct_per_round_all",
  "bankroll_floor_rub",
  "liability_amount_rub",
];
const RESPONSIBLE_NUM: NumericField[] = [
  "reality_check_default_minutes",
  "self_exclusion_min_hours",
  "timeout_max_hours",
  "limit_loosening_delay_hours",
];
const RESPONSIBLE_BOOL: BoolField[] = [
  "deposit_limit_enabled",
  "loss_limit_enabled",
  "wager_limit_enabled",
  "session_limit_enabled",
];
const PAYOUT_FIELDS: NumericField[] = [
  "min_withdrawal_rub",
  "withdrawal_auto_approve_max_rub",
  "withdrawal_manual_review_min_rub",
  "withdrawal_daily_limit_rub",
  "withdrawal_hourly_limit_rub",
];

function pickChanged(current: SettingsForm, baseline: SettingsForm, keys: NumericField[]): boolean {
  return keys.some((key) => current[key] !== baseline[key]);
}

export function countDirtySections(
  current: SettingsForm,
  baseline: SettingsForm,
  cashback: CashbackTierRow[],
  cashbackBase: CashbackTierRow[],
  commission: CommissionTierRow[],
  commissionBase: CommissionTierRow[],
  bonuses: BonusRow[] = [],
  bonusesBase: BonusRow[] = [],
): number {
  let count = 0;
  if (pickChanged(current, baseline, COMMISSION_FIELDS)) count += 1;
  if (
    pickChanged(current, baseline, LIMIT_FIELDS) ||
    JSON.stringify(current.per_game_limits) !== JSON.stringify(baseline.per_game_limits) ||
    JSON.stringify(current.max_rounds_per_player_per_day) !== JSON.stringify(baseline.max_rounds_per_player_per_day)
  ) {
    count += 1;
  }
  if (pickChanged(current, baseline, HOLDEM_FIELDS)) count += 1;
  if (pickChanged(current, baseline, DRAUGHTS_FIELDS)) count += 1;
  if (pickChanged(current, baseline, JACKPOT_FIELDS)) count += 1;
  if (pickChanged(current, baseline, ROULETTE_TABLE_FIELDS)) count += 1;
  if (pickChanged(current, baseline, CLAN_FIELDS) || current.clans_enabled !== baseline.clans_enabled) count += 1;
  if (pickChanged(current, baseline, FIXED_ROOM_FIELDS)) count += 1;
  if (pickChanged(current, baseline, CLAN_WAR_FIELDS)) count += 1;
  if (pickChanged(current, baseline, BANKROLL_FIELDS)) count += 1;
  if (
    JSON.stringify(cashback) !== JSON.stringify(cashbackBase) ||
    JSON.stringify(commission) !== JSON.stringify(commissionBase) ||
    JSON.stringify(bonuses) !== JSON.stringify(bonusesBase)
  ) {
    count += 1;
  }
  if (
    pickChanged(current, baseline, RESPONSIBLE_NUM) ||
    RESPONSIBLE_BOOL.some((key) => current[key] !== baseline[key])
  ) {
    count += 1;
  }
  if (pickChanged(current, baseline, PAYOUT_FIELDS)) count += 1;
  if (
    current.seed_rotation_allowed !== baseline.seed_rotation_allowed ||
    JSON.stringify(current.provably_fair_enabled) !== JSON.stringify(baseline.provably_fair_enabled)
  ) {
    count += 1;
  }
  if (JSON.stringify(current.enabled_games) !== JSON.stringify(baseline.enabled_games)) count += 1;
  return count;
}

export function isFormDirty(
  current: SettingsForm,
  baseline: SettingsForm,
  cashback: CashbackTierRow[],
  cashbackBase: CashbackTierRow[],
  commission: CommissionTierRow[],
  commissionBase: CommissionTierRow[],
  bonuses: BonusRow[] = [],
  bonusesBase: BonusRow[] = [],
): boolean {
  return (
    JSON.stringify(current) !== JSON.stringify(baseline) ||
    JSON.stringify(cashback) !== JSON.stringify(cashbackBase) ||
    JSON.stringify(commission) !== JSON.stringify(commissionBase) ||
    JSON.stringify(bonuses) !== JSON.stringify(bonusesBase)
  );
}

const EXAMPLE_BANK_RUB = 10_000;
const EXAMPLE_DEPOSIT_RUB = 1_000;

export function liveCommissionExample(form: SettingsForm): {
  bankRub: number;
  stakeRub: number;
  commissionRub: number;
  creatorRub: number;
  evPct: number;
} | null {
  const rate = parseRequiredNumber(form.commission_rate_wagering_active);
  const creator = parseRequiredNumber(form.creator_cut_percent_wagering_active);
  const l1 = parseRequiredNumber(form.referral_l1_percent_wagering_active);
  const l2 = parseRequiredNumber(form.referral_l2_percent_wagering_active);
  if (rate == null || creator == null || l1 == null || l2 == null) return null;
  if (rate < 0 || creator + l1 + l2 > rate) return null;
  const stakeRub = EXAMPLE_BANK_RUB / 2;
  const commissionRub = (stakeRub * rate) / 100;
  const creatorRub = (stakeRub * creator) / 100;
  return {
    bankRub: EXAMPLE_BANK_RUB,
    stakeRub,
    commissionRub,
    creatorRub,
    // Fair 50/50: EV = −commission/2. As % of the bank that matches «300 ₽ → −1.5%».
    evPct: -((commissionRub / 2) / EXAMPLE_BANK_RUB) * 100,
  };
}

export function liveWageringExample(form: SettingsForm): {
  deposit: number;
  houseTake: number;
  stakeNeeded: number | null;
  commission: number | null;
} | null {
  const wagering = parseRequiredNumber(form.wagering_percent);
  const commission = parseRequiredNumber(form.commission_rate_wagering_active);
  if (wagering == null || wagering < 0) return null;
  return {
    deposit: EXAMPLE_DEPOSIT_RUB,
    houseTake: (EXAMPLE_DEPOSIT_RUB * wagering) / 100,
    stakeNeeded: commission != null && commission > 0 ? (EXAMPLE_DEPOSIT_RUB * wagering) / commission : null,
    commission,
  };
}

export type CommissionShareBase = Pick<
  SettingsForm,
  | "commission_rate_wagering_active"
  | "commission_rate_wagering_complete"
  | "creator_cut_percent_wagering_active"
  | "referral_l1_percent_wagering_active"
  | "referral_l2_percent_wagering_active"
  | "creator_cut_percent_wagering_complete"
  | "referral_l1_percent_wagering_complete"
  | "referral_l2_percent_wagering_complete"
>;

export type ScaledStakeShares = {
  creator: number;
  l1: number;
  l2: number;
  house: number;
};

export function scaleStakeSharePercents(
  actualRate: number,
  baseRate: number,
  creator: number,
  l1: number,
  l2: number,
): ScaledStakeShares | null {
  if (![actualRate, baseRate, creator, l1, l2].every(Number.isFinite)) return null;
  if (actualRate < 0 || baseRate < 0 || creator < 0 || l1 < 0 || l2 < 0) return null;
  if (baseRate <= 0) {
    if (creator + l1 + l2 > actualRate) return null;
    return { creator, l1, l2, house: actualRate - creator - l1 - l2 };
  }
  const scale = actualRate === baseRate ? 1 : actualRate / baseRate;
  const scaledCreator = creator * scale;
  const scaledL1 = l1 * scale;
  const scaledL2 = l2 * scale;
  if (scaledCreator + scaledL1 + scaledL2 > actualRate + 1e-9) return null;
  return {
    creator: scaledCreator,
    l1: scaledL1,
    l2: scaledL2,
    house: actualRate - scaledCreator - scaledL1 - scaledL2,
  };
}

function formatSharePct(value: number): string {
  const rounded = Number((Math.round(value * 1000) / 1000).toFixed(3));
  return String(rounded).replace(".", ",");
}

export function formatLevelShares(shares: ScaledStakeShares | null): string {
  if (!shares) return "—";
  return `${formatSharePct(shares.creator)} · ${formatSharePct(shares.l1)} · ${formatSharePct(shares.l2)} · ${formatSharePct(shares.house)}`;
}

export function formatShareBreakdown(shares: ScaledStakeShares): string {
  return `Creator ${formatSharePct(shares.creator)}% · L1 ${formatSharePct(shares.l1)}% · L2 ${formatSharePct(shares.l2)}% · казино ${formatSharePct(shares.house)}%`;
}

export function scaledSharesForProfile(
  shareBase: CommissionShareBase,
  profile: "wagering_active" | "wagering_complete",
  actualRateRaw: string,
): ScaledStakeShares | null {
  const actual = parseRequiredNumber(actualRateRaw);
  if (actual == null) return null;
  const suffix = profile === "wagering_active" ? "wagering_active" : "wagering_complete";
  const base = parseRequiredNumber(shareBase[`commission_rate_${suffix}`]);
  const creator = parseRequiredNumber(shareBase[`creator_cut_percent_${suffix}`]);
  const l1 = parseRequiredNumber(shareBase[`referral_l1_percent_${suffix}`]);
  const l2 = parseRequiredNumber(shareBase[`referral_l2_percent_${suffix}`]);
  if (base == null || creator == null || l1 == null || l2 == null) return null;
  return scaleStakeSharePercents(actual, base, creator, l1, l2);
}

export const SECTION_HINTS: Record<SettingsSectionId, { title: string; body: string }> = {
  commission: {
    title: "Комиссия считается с проигравшей ставки",
    body: "Не с банка и не с оборота. Доли создателя и рефералов берутся из той же базы и не могут превысить комиссию профиля. На ступенях сетки они падают вместе с комиссией игрока.",
  },
  limits: {
    title: "Глобальные границы и шаг",
    body: "Пустые min/max в таблице игры = эти глобальные лимиты. Раундов в день: пусто или 0 = без ограничения.",
  },
  holdem: {
    title: "Кэш-стол Hold'em",
    body: "Бай-ин в ₽ = стек. Рейк берётся с банка руки с потолком, не с проигравшей ставки дуэли. Таймаут хода — автофолд, если нельзя чекнуть.",
  },
  draughts: {
    title: "Русские шашки",
    body: "Двое ставят одну сумму. Ничья возвращает обе. Победа — банк минус рейк холдема. Таймаут хода сдаёт ставку, бота нет.",
  },
  jackpot: {
    title: "Джекпот-рулетка",
    body: "Сбор 5 минут с первой ставки, до 30 игроков, рейк с банка. Билеты пропорциональны ставке. Ролл фиксируется в момент открытия раунда.",
  },
  roulette_table: {
    title: "Общий стол европейской рулетки",
    body: "Одно колесо на всех против дома, не джекпот. HMAC лунки от round_id. Пустой раунд не крутится.",
  },
  clans: {
    title: "Команды игроков",
    body: "Клан не держит баланс. Топ по обороту за московскую неделю. Вступление только по коду, потолок состава 2–50.",
  },
  fixed_rooms: {
    title: "Комнаты 2–N",
    body: "Одинаковая ставка на всех, N мест. HMAC-SHA256 по сиду и порядку посадки. Недобор до таймаута — полный возврат, не частичный розыгрыш. Пустое место можно заполнить ботом.",
  },
  clan_wars: {
    title: "Клан vs клан",
    body: "Ставки с кошельков игроков, не с казны клана. HMAC выбирает клан-победитель; банк минус рейк делится поровну между бойцами победителей.",
  },
  bankroll: {
    title: "Защита банка",
    body: "Порог и обязательства 0 = выключено. Макс. выигрыш — процент от текущего банка дома, не от ставки игрока.",
  },
  tiers: {
    title: "Уровни по недельному обороту",
    body: "Первая ступень = комиссия из блока «Комиссия и доли». Creator, L1 и L2 на следующих ступенях режутся тем же коэффициентом, что комиссия игрока. Колонки «Доли до/после» только для чтения.",
  },
  responsible: {
    title: "Лимиты игрока",
    body: "Тумблеры по умолчанию выключены. Ужесточение сразу, ослабление — после задержки. Сами лимиты игрока в игре ещё не применяются.",
  },
  payouts: {
    title: "Выводы создателя",
    body: "0 = порог выключен. Пока все заявки обрабатываются вручную, даже если автовывод задан.",
  },
  fairness: {
    title: "Provably fair",
    body: "Ротация сидов раскрывает предыдущий серверный сид. Включение по играм не меняет RNG, пока игра это не читает.",
  },
  games: {
    title: "Что доступно в боте",
    body: "Выключенная игра пропадает из меню. Раффл по умолчанию выключен — не включайте без отдельной готовности.",
  },
  danger: {
    title: "Разрушительные действия",
    body: "Выключение всех игр попадает в сохранение настроек и требует причину. Отзыв кабинета создателя выполняется сразу.",
  },
};

function selfCheckExamples(): void {
  const wager = liveWageringExample({
    wagering_percent: "21",
    commission_rate_wagering_active: "15",
  } as SettingsForm);
  if (!wager || wager.houseTake !== 210 || wager.stakeNeeded !== 1400) {
    throw new Error("liveWageringExample: 21% of 1000 must be 210 ₽, 1400 ₽ stakes at 15%");
  }
  const house = liveCommissionExample({
    commission_rate_wagering_active: "6",
    creator_cut_percent_wagering_active: "1.2",
    referral_l1_percent_wagering_active: "0",
    referral_l2_percent_wagering_active: "0",
  } as SettingsForm);
  if (!house || house.commissionRub !== 300 || house.creatorRub !== 60 || house.evPct !== -1.5) {
    throw new Error("liveCommissionExample: bank 10000 at 6%/1.2% must be 300/60/−1.5%");
  }
  const same = scaleStakeSharePercents(15, 15, 3, 2, 2);
  if (!same || same.creator !== 3 || same.l1 !== 2 || same.l2 !== 2 || same.house !== 8) {
    throw new Error("scaleStakeSharePercents: same rate must keep shares");
  }
  const scaled = scaleStakeSharePercents(10, 15, 3, 2, 2);
  if (!scaled || scaled.creator !== 2) {
    throw new Error("scaleStakeSharePercents: 15→10 creator 3 must become 2");
  }
  if (Math.abs(scaled.l1 - 4 / 3) > 1e-9 || Math.abs(scaled.l2 - 4 / 3) > 1e-9) {
    throw new Error("scaleStakeSharePercents: 15→10 L1/L2 must be 4/3");
  }
  const grown = scaleStakeSharePercents(18, 15, 3, 2, 2);
  if (
    !grown ||
    Math.abs(grown.creator - 3.6) > 1e-9 ||
    Math.abs(grown.l1 - 2.4) > 1e-9 ||
    Math.abs(grown.l2 - 2.4) > 1e-9
  ) {
    throw new Error("scaleStakeSharePercents: 15→18 must grow shares");
  }
}
selfCheckExamples();
