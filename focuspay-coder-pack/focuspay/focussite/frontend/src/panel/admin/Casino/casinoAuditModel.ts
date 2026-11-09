import type { AdminCasinoSettingsAuditRow } from "@/panel/lib/adminApi";

export const AUDIT_RETENTION_NOTE =
  "Записи не удаляются автоматически: в базе нет срока хранения и нет задания очистки.";

export const AUDIT_WINDOWS = [
  { id: "24h", label: "24ч" },
  { id: "7d", label: "7д" },
  { id: "30d", label: "30д" },
  { id: "custom", label: "свой" },
] as const;

export type AuditWindowId = (typeof AUDIT_WINDOWS)[number]["id"];

export const AUDIT_KEY_LABELS: Record<string, string> = {
  commission_rate: "Комиссия",
  commission_rate_wagering_active: "Комиссия при отыгрыше",
  commission_rate_wagering_complete: "Комиссия после отыгрыша",
  wagering_percent: "Отыгрыш",
  creator_cut_percent: "Доля создателя",
  creator_cut_percent_wagering_active: "Creator при отыгрыше",
  creator_cut_percent_wagering_complete: "Creator после отыгрыша",
  referral_l1_percent: "Реферал L1",
  referral_l2_percent: "Реферал L2",
  referral_l1_percent_wagering_active: "Реферал L1 при отыгрыше",
  referral_l2_percent_wagering_active: "Реферал L2 при отыгрыше",
  referral_l1_percent_wagering_complete: "Реферал L1 после отыгрыша",
  referral_l2_percent_wagering_complete: "Реферал L2 после отыгрыша",
  min_bet_rub: "Мин. ставка",
  max_bet_rub: "Макс. ставка",
  bet_step_rub: "Шаг ставки",
  min_withdrawal_rub: "Мин. вывод",
  max_profit_pct_per_round: "Макс. выигрыш за раунд",
  max_profit_pct_per_round_all: "Макс. выигрыш всех",
  bankroll_floor_rub: "Порог банкролла",
  liability_amount_rub: "Потолок обязательств",
  max_concurrent_games_per_player: "Одновременные игры",
  pending_invite_ttl_minutes: "TTL приглашения",
  move_timeout_minutes: "Таймаут хода",
  holdem_small_blind_rub: "Холдем: малый блайнд",
  holdem_big_blind_rub: "Холдем: большой блайнд",
  holdem_rake_percent: "Холдем: рейк",
  holdem_rake_cap_rub: "Холдем: потолок рейка",
  holdem_action_timeout_seconds: "Холдем: таймаут хода",
  draughts_move_timeout_seconds: "Шашки: таймаут хода",
  holdem_min_buyin_bb: "Холдем: мин. бай-ин BB",
  holdem_max_buyin_bb: "Холдем: макс. бай-ин BB",
  jackpot_collect_seconds: "Джекпот: сбор (сек)",
  jackpot_max_players: "Джекпот: макс. игроков",
  jackpot_rake_percent: "Джекпот: рейк",
  roulette_table_collect_seconds: "Рулетка стол: сбор (сек)",
  roulette_table_max_players: "Рулетка стол: макс. игроков",
  clans_enabled: "Кланы",
  clan_max_members: "Кланы: макс. состав",
  fixed_room_rake_percent: "Комнаты: рейк",
  fixed_room_max_seats: "Комнаты: макс. мест",
  fixed_room_collect_seconds: "Комнаты: набор",
  clan_war_rake_percent: "Война кланов: рейк",
  clan_war_max_fighters: "Война кланов: бойцов",
  clan_war_collect_seconds: "Война кланов: набор",
  commission_cap_rub: "Потолок комиссии",
  commission_min_rub: "Мин. комиссия",
  deposit_limit_enabled: "Лимит депозита",
  loss_limit_enabled: "Лимит проигрыша",
  wager_limit_enabled: "Лимит ставок",
  session_limit_enabled: "Лимит сессии",
  reality_check_default_minutes: "Напоминание",
  self_exclusion_min_hours: "Самоисключение",
  timeout_max_hours: "Макс. тайм-аут",
  limit_loosening_delay_hours: "Задержка ослабления",
  withdrawal_auto_approve_max_rub: "Автовывод до",
  withdrawal_manual_review_min_rub: "Ручная проверка от",
  withdrawal_daily_limit_rub: "Дневной лимит вывода",
  withdrawal_hourly_limit_rub: "Часовой лимит вывода",
  enabled_games: "Включённые игры",
  cashback_volume_tiers: "Сетка кешбека",
  commission_volume_tiers: "Сетка комиссии",
  level_reach_bonuses: "Бонус за уровень",
  per_game_limits: "Лимиты по играм",
  max_rounds_per_player_per_day: "Раундов в день",
  provably_fair_enabled: "Provably fair",
  seed_rotation_allowed: "Ротация сидов",
};

export function auditKeyLabel(key: string): string {
  return AUDIT_KEY_LABELS[key] ?? key;
}

export function unwrapAuditJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed || (trimmed[0] !== "{" && trimmed[0] !== "[" && trimmed[0] !== '"')) return value;
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

export function formatAuditValue(value: unknown): string {
  const parsed = unwrapAuditJson(value);
  if (parsed == null) return "—";
  if (typeof parsed === "boolean") return parsed ? "да" : "нет";
  if (typeof parsed === "number" || typeof parsed === "bigint") return String(parsed);
  if (typeof parsed === "string") return parsed;
  if (Array.isArray(parsed)) return JSON.stringify(parsed);
  if (typeof parsed === "object") {
    const record = parsed as Record<string, unknown>;
    const keys = Object.keys(record);
    if (keys.length === 1 && "percent" in record) return `${record.percent}%`;
    if (keys.length === 1 && "amount" in record) return `${record.amount} ₽`;
    if (keys.length === 1 && "enabled" in record) return record.enabled ? "да" : "нет";
    if (keys.length === 1 && "value" in record) return String(record.value);
    return JSON.stringify(parsed);
  }
  return String(parsed);
}

export type AuditBatch = {
  batch_id: string;
  changed_at: string;
  changed_by: string;
  reason: string;
  items: AdminCasinoSettingsAuditRow[];
};

export function groupAuditBatches(rows: AdminCasinoSettingsAuditRow[]): AuditBatch[] {
  const order: string[] = [];
  const byId = new Map<string, AuditBatch>();
  for (const row of rows) {
    const id = String(row.batch_id);
    let batch = byId.get(id);
    if (!batch) {
      batch = {
        batch_id: id,
        changed_at: row.changed_at,
        changed_by: row.changed_by,
        reason: row.reason,
        items: [],
      };
      byId.set(id, batch);
      order.push(id);
    }
    batch.items.push(row);
  }
  return order.map((id) => byId.get(id)!);
}

function selfCheck(): void {
  if (formatAuditValue({ percent: 15 }) !== "15%") {
    throw new Error("formatAuditValue: percent wrapper");
  }
  if (formatAuditValue({ amount: 0 }) !== "0 ₽") {
    throw new Error("formatAuditValue: amount wrapper");
  }
  if (formatAuditValue('{"percent": 2.0}') !== "2%") {
    throw new Error("formatAuditValue: stringified JSON percent");
  }
  const grouped = groupAuditBatches([
    {
      id: 2,
      batch_id: "aaa",
      key: "min_bet_rub",
      old_value: { amount: 10 },
      new_value: { amount: 88 },
      changed_by: "123",
      changed_at: "2026-08-28T21:00:00Z",
      reason: "клик",
    },
    {
      id: 1,
      batch_id: "aaa",
      key: "commission_rate",
      old_value: { percent: 15 },
      new_value: { percent: 13.23 },
      changed_by: "123",
      changed_at: "2026-08-28T21:00:00Z",
      reason: "клик",
    },
    {
      id: 3,
      batch_id: "bbb",
      key: "min_bet_rub",
      old_value: { amount: 88 },
      new_value: { amount: 10 },
      changed_by: "123",
      changed_at: "2026-08-28T20:00:00Z",
      reason: "откат",
    },
  ]);
  if (grouped.length !== 2) throw new Error("groupAuditBatches: one row per save");
  if (grouped[0].batch_id !== "aaa" || grouped[0].items.length !== 2) {
    throw new Error("groupAuditBatches: first save keeps field order and count");
  }
  if (grouped[1].items.length !== 1) throw new Error("groupAuditBatches: second save");
}

selfCheck();
