/** V2 baccarat street deal: first card around the table, then second, then thirds. */

export const BACCARA_CARD_MS = 420;
export const BACCARA_STREET_GAP_MS = 650;
export const BACCARA_RESULT_BEAT_MS = 450;

export type BaccaratStreetStep = { seat: number; index: number };

export function baccaratCardValue(code: string): number {
  const text = String(code || "").trim();
  const rank = text.length >= 2 ? text.slice(0, -1) : "";
  if (rank === "A") return 1;
  if (rank === "10" || rank === "J" || rank === "Q" || rank === "K") return 0;
  const n = Number(rank);
  return n >= 2 && n <= 9 ? n : 0;
}

export function baccaratHandScore(codes: string[]): number {
  return codes.reduce((sum, code) => sum + baccaratCardValue(code), 0) % 10;
}

export function faceCardCodes(codes: string[] | undefined): string[] {
  return (codes || []).map(String).filter((code) => code && code !== "back");
}

export function baccaratHandsFromSeats(
  seats: Array<{ seat_no: number; cards?: string[] | null }>,
  options?: { keepBacks?: boolean },
): Record<number, string[]> {
  const keepBacks = Boolean(options?.keepBacks);
  const hands: Record<number, string[]> = {};
  for (const seat of seats) {
    const cards = (seat.cards || [])
      .map(String)
      .filter((code) => code && (keepBacks || code !== "back"));
    if (!cards.length) continue;
    hands[seat.seat_no] = cards;
  }
  return hands;
}

export function baccaratStreetSteps(hands: Record<number, string[]>): BaccaratStreetStep[] {
  const seats = Object.keys(hands)
    .map(Number)
    .filter((seat) => Number.isFinite(seat) && (hands[seat]?.length || 0) > 0)
    .sort((a, b) => a - b);
  const maxLen = seats.reduce((max, seat) => Math.max(max, hands[seat].length), 0);
  const steps: BaccaratStreetStep[] = [];
  for (let index = 0; index < maxLen; index += 1) {
    for (const seat of seats) {
      if (hands[seat].length > index) steps.push({ seat, index });
    }
  }
  return steps;
}

export function baccaratStreetWaitMs(steps: BaccaratStreetStep[], nextRevealed: number): number {
  if (nextRevealed < 0 || nextRevealed >= steps.length) return 0;
  if (nextRevealed === 0) return BACCARA_CARD_MS;
  const prev = steps[nextRevealed - 1];
  const next = steps[nextRevealed];
  if (prev && next && next.index !== prev.index) return BACCARA_STREET_GAP_MS;
  return BACCARA_CARD_MS;
}

export function baccaratStreetRevealMs(input: {
  steps: BaccaratStreetStep[];
  skipMotion?: boolean;
  includeOutcomeBeat?: boolean;
}): number {
  if (input.skipMotion) return 0;
  let total = 0;
  for (let index = 0; index < input.steps.length; index += 1) {
    total += baccaratStreetWaitMs(input.steps, index);
  }
  if (input.includeOutcomeBeat === false) return total;
  return total + BACCARA_RESULT_BEAT_MS;
}

export function baccaratShownCount(steps: BaccaratStreetStep[], revealed: number, seat: number): number {
  let count = 0;
  const limit = Math.min(Math.max(0, revealed), steps.length);
  for (let index = 0; index < limit; index += 1) {
    if (steps[index].seat === seat) count += 1;
  }
  return count;
}

export function baccaratVisibleCards(full: string[], shown: number): string[] {
  return full.slice(0, Math.max(0, shown));
}

export function baccaratStreetAttr(
  steps: BaccaratStreetStep[],
  revealed: number,
  resultReady: boolean,
): string {
  if (!steps.length) return "";
  if (resultReady) return "outcome";
  if (revealed <= 0) return "1";
  const last = steps[Math.min(revealed, steps.length) - 1];
  return String((last?.index ?? 0) + 1);
}

export function baccaratElapsedMs(dealtAt: string | undefined | null, nowMs: number): number {
  if (!dealtAt) return 0;
  const started = Date.parse(dealtAt);
  if (!Number.isFinite(started)) return 0;
  return Math.max(0, nowMs - started);
}

export function baccaratRevealedAfter(
  steps: BaccaratStreetStep[],
  elapsedMs: number,
): { revealed: number; resultReady: boolean; nextWaitMs: number } {
  if (!steps.length) return { revealed: 0, resultReady: false, nextWaitMs: 0 };
  if (!Number.isFinite(elapsedMs) || elapsedMs === Number.POSITIVE_INFINITY) {
    return { revealed: steps.length, resultReady: true, nextWaitMs: 0 };
  }
  let t = 0;
  for (let index = 0; index < steps.length; index += 1) {
    const wait = baccaratStreetWaitMs(steps, index);
    if (elapsedMs < t + wait) {
      return { revealed: index, resultReady: false, nextWaitMs: t + wait - elapsedMs };
    }
    t += wait;
  }
  const beatEnd = t + BACCARA_RESULT_BEAT_MS;
  if (elapsedMs < beatEnd) {
    return { revealed: steps.length, resultReady: false, nextWaitMs: beatEnd - elapsedMs };
  }
  return { revealed: steps.length, resultReady: true, nextWaitMs: 0 };
}

export function baccaratRoundKey(
  tableId: string,
  commit: string | undefined,
  hands: Record<number, string[]>,
  dealtAt?: string,
): string {
  const seats = Object.keys(hands)
    .map(Number)
    .sort((a, b) => a - b);
  const packed = seats.map((seat) => `${seat}:${(hands[seat] || []).join(",")}`).join("|");
  return `${tableId}|${commit || ""}|${packed}|${dealtAt || ""}`;
}

export const BLACKJACK_STREET_CARDS = 2;

const BLACKJACK_HOLE_OPEN_STATUSES = new Set([
  "finished",
  "cancelled",
  "expired",
  "manual_review",
  "outcome_committed",
  "settled",
  "settling",
]);

/** Deal phase "scoring" still hides the other seats. Faces open at showdown. */
export function blackjackHolesOpen(status: string | undefined, phase: string | undefined): boolean {
  if (status && BLACKJACK_HOLE_OPEN_STATUSES.has(status)) return true;
  return phase === "draw_choice" || phase === "settled";
}

export function blackjackCardValue(code: string): number {
  const text = String(code || "").trim();
  const rank = text.length >= 2 ? text.slice(0, -1) : "";
  if (rank === "A") return 11;
  if (rank === "10" || rank === "J" || rank === "Q" || rank === "K") return 10;
  const n = Number(rank);
  return n >= 2 && n <= 10 ? n : 0;
}

export function blackjackHandScore(codes: string[]): number {
  let total = 0;
  let aces = 0;
  for (const code of codes) {
    const rank = String(code || "").trim();
    const pip = rank.length >= 2 ? rank.slice(0, -1) : "";
    if (pip === "A") {
      aces += 1;
      total += 11;
    } else if (pip === "10" || pip === "J" || pip === "Q" || pip === "K") {
      total += 10;
    } else {
      const n = Number(pip);
      if (n >= 2 && n <= 10) total += n;
    }
  }
  while (total > 21 && aces) {
    total -= 10;
    aces -= 1;
  }
  return total;
}

export function blackjackStreetHands(hands: Record<number, string[]>): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  for (const [seat, cards] of Object.entries(hands)) {
    out[Number(seat)] = cards.slice(0, BLACKJACK_STREET_CARDS);
  }
  return out;
}

export function blackjackRoundKey(
  tableId: string,
  commit: string | undefined,
  hands: Record<number, string[]>,
  dealtAt?: string,
): string {
  return baccaratRoundKey(tableId, commit, blackjackStreetHands(hands), dealtAt);
}

export function blackjackVisibleCards(full: string[], shown: number, streetDone: boolean): string[] {
  if (streetDone) return full;
  return full.slice(0, Math.max(0, shown));
}

export function baccaratDealingLabel(street: string): string {
  if (street === "2") return "Раздача: вторая карта…";
  if (street === "3") return "Раздача: третья карта…";
  return "Раздача: первая карта…";
}
