/** Keep a seated V2 table in the lobby list while it is still playing or just finished. */

export type V2LobbyMergeRow = {
  table_id: string;
  is_seated: boolean;
  status: string;
  game_type?: string;
  game_state: { phase?: string };
  roster: Array<{ cards?: string[] | null }>;
};

export function keepSeatedV2PlayTable(row: V2LobbyMergeRow): boolean {
  if (!row.is_seated) return false;
  if (row.status === "running" || row.status === "tie_break_running" || row.status === "finished") return true;
  return row.game_state.phase === "draw_choice";
}

function faceCardCount(table: V2LobbyMergeRow): number {
  return table.roster.reduce((n, seat) => {
    const cards = seat.cards || [];
    return n + cards.filter((code) => code && code !== "back").length;
  }, 0);
}

export function mergeV2LobbyTables<T extends V2LobbyMergeRow>(
  list: T[],
  prev: T[],
  gameType?: string,
): T[] {
  const prevById = new Map(prev.map((row) => [row.table_id, row]));
  const seen = new Set<string>();
  const out: T[] = [];
  for (const row of list) {
    const old = prevById.get(row.table_id);
    if (old?.is_seated && faceCardCount(old) > faceCardCount(row)) {
      out.push(old);
    } else {
      out.push(row);
    }
    seen.add(row.table_id);
  }
  for (const old of prev) {
    if (seen.has(old.table_id)) continue;
    if (gameType && old.game_type && old.game_type !== gameType) continue;
    if (keepSeatedV2PlayTable(old)) {
      out.unshift(old);
      seen.add(old.table_id);
    }
  }
  return out;
}
