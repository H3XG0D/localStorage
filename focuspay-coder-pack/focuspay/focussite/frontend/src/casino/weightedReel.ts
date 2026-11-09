/** Weighted jackpot/raffle reel: ticket share stays, faces round-robin instead of clumps. */

export const WEIGHTED_REEL_SLOT_COUNT = 100;
export const WEIGHTED_REEL_WINNER_INDEX = 80;
export const WEIGHTED_REEL_SPIN_MS = 10500;

export function buildWeightedReel<T extends { user_id: number }>(
  players: T[],
  weightOf: (player: T) => number,
  winnerId: number | null,
  slotCount = WEIGHTED_REEL_SLOT_COUNT,
  winnerIndex = WEIGHTED_REEL_WINNER_INDEX,
): T[] {
  if (!players.length || slotCount <= 0) return [];
  const unique: T[] = [];
  const seen = new Set<number>();
  for (const player of players) {
    if (seen.has(player.user_id)) continue;
    seen.add(player.user_id);
    unique.push(player);
  }
  const total = unique.reduce((sum, row) => sum + Math.max(weightOf(row), 0), 0) || 1;
  const remaining = unique.map((player) => Math.max(1, Math.round((Math.max(weightOf(player), 0) / total) * slotCount)));
  let sum = remaining.reduce((acc, n) => acc + n, 0);
  while (sum > slotCount) {
    const i = remaining.findIndex((n) => n > 1);
    if (i < 0) break;
    remaining[i] -= 1;
    sum -= 1;
  }
  while (sum < slotCount) {
    remaining[sum % remaining.length] += 1;
    sum += 1;
  }

  const slots: T[] = [];
  while (slots.length < slotCount) {
    let placed = false;
    for (let i = 0; i < unique.length && slots.length < slotCount; i += 1) {
      if (remaining[i] <= 0) continue;
      slots.push(unique[i]);
      remaining[i] -= 1;
      placed = true;
    }
    if (!placed) break;
  }
  while (slots.length < slotCount) {
    slots.push(unique[slots.length % unique.length]);
  }
  slots.length = slotCount;
  if (winnerId != null) {
    const winner = unique.find((row) => row.user_id === winnerId);
    const at = Math.min(Math.max(winnerIndex, 0), slotCount - 1);
    if (winner) slots[at] = winner;
  }
  return slots;
}
