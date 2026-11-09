/** Sequential house-card deal. Outcome (toast, banner, wallet) waits until this finishes. */

export const HOUSE_CARD_DEAL_MS = 280;
export const HOUSE_CARD_RESULT_BEAT_MS = 450;

export function cardsFromPlayResult(
  result: {
    player_cards?: unknown;
    house_cards?: unknown;
    rng?: { player_cards?: unknown; house_cards?: unknown };
  } | null,
  side: "player" | "house",
): string[] {
  if (!result) return [];
  const raw = side === "player" ? result.player_cards : result.house_cards;
  if (Array.isArray(raw) && raw.length) return raw.map(String);
  const nested = side === "player" ? result.rng?.player_cards : result.rng?.house_cards;
  return Array.isArray(nested) ? nested.map(String) : [];
}

export function houseCardsRevealMs(input: {
  playerCount: number;
  houseCount: number;
  fromPlayer?: number;
  fromHouse?: number;
  liveHouse?: boolean;
  skipMotion?: boolean;
  includeOutcomeBeat?: boolean;
}): number {
  if (input.skipMotion) return 0;
  const playerLeft = Math.max(0, input.playerCount - (input.fromPlayer ?? 0));
  const houseLeft = input.liveHouse ? 0 : Math.max(0, input.houseCount - (input.fromHouse ?? 0));
  const deal = (playerLeft + houseLeft) * HOUSE_CARD_DEAL_MS;
  if (input.liveHouse || input.includeOutcomeBeat === false) return deal;
  return deal + HOUSE_CARD_RESULT_BEAT_MS;
}
