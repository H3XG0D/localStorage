/**
 * European roulette table data. Mirrors `casino_roulette.py` on the backend, which
 * stays the only authority for the drawn pocket and the money — this file exists so
 * the wheel can be drawn and the landing angle computed, nothing more.
 */

export type RoulettePocketColor = "green" | "red" | "black";
export type RouletteOutsideBet =
  | "red"
  | "black"
  | "zero"
  | "even"
  | "odd"
  | "low"
  | "high"
  | "dozen1"
  | "dozen2"
  | "dozen3"
  | "col1"
  | "col2"
  | "col3";
export type RouletteBetKey = RouletteOutsideBet | string;

export const ROULETTE_POCKET_COUNT = 37;
/** European felt: 36 units come back on a 1-pocket hit (35:1 plus the stake). */
export const ROULETTE_STRAIGHT_RETURN = ROULETTE_POCKET_COUNT - 1;
export const ROULETTE_MAX_COVER = ROULETTE_POCKET_COUNT - 1;

/** Physical single-zero wheel, clockwise from the green zero. */
export const ROULETTE_WHEEL_ORDER: readonly number[] = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34,
  6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
  24, 16, 33, 1, 20, 14, 31, 9, 22, 18,
  29, 7, 28, 12, 35, 3, 26,
];

const RED_POCKETS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
const BLACK_POCKETS = new Set([2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]);
const EVEN_POCKETS = Array.from({ length: 18 }, (_, i) => (i + 1) * 2);
const ODD_POCKETS = Array.from({ length: 18 }, (_, i) => i * 2 + 1);
const LOW_POCKETS = Array.from({ length: 18 }, (_, i) => i + 1);
const HIGH_POCKETS = Array.from({ length: 18 }, (_, i) => i + 19);
const DOZEN1_POCKETS = Array.from({ length: 12 }, (_, i) => i + 1);
const DOZEN2_POCKETS = Array.from({ length: 12 }, (_, i) => i + 13);
const DOZEN3_POCKETS = Array.from({ length: 12 }, (_, i) => i + 25);
const COL1_POCKETS = Array.from({ length: 12 }, (_, i) => i * 3 + 1);
const COL2_POCKETS = Array.from({ length: 12 }, (_, i) => i * 3 + 2);
const COL3_POCKETS = Array.from({ length: 12 }, (_, i) => i * 3 + 3);

const WHEEL_INDEX = new Map(ROULETTE_WHEEL_ORDER.map((pocket, index) => [pocket, index]));

export interface RouletteBetSpec {
  key: RouletteBetKey;
  title: string;
  ariaLabel: string;
  odds: string;
  /** Total return on the stake: 1:1 pays ×2, 35:1 pays ×36. */
  payoutMultiplier: number;
  /** Profit per unit staked, the number casinos print on the felt. */
  profitRatio: number;
  pockets: number[];
}

function namedBet(
  key: RouletteOutsideBet,
  title: string,
  odds: string,
  payoutMultiplier: number,
  pockets: number[],
): RouletteBetSpec {
  return {
    key,
    title,
    ariaLabel: `Ставка на ${title.toLowerCase()}, выплата ${odds.replace(":", " к ")}`,
    odds,
    payoutMultiplier,
    profitRatio: payoutMultiplier - 1,
    pockets,
  };
}

export const ROULETTE_BETS: Record<RouletteOutsideBet, RouletteBetSpec> = {
  red: namedBet("red", "Красное", "1:1", 2, [...RED_POCKETS].sort((a, b) => a - b)),
  black: namedBet("black", "Чёрное", "1:1", 2, [...BLACK_POCKETS].sort((a, b) => a - b)),
  zero: namedBet("zero", "Зеро", "35:1", 36, [0]),
  even: namedBet("even", "Чёт", "1:1", 2, EVEN_POCKETS),
  odd: namedBet("odd", "Нечет", "1:1", 2, ODD_POCKETS),
  low: namedBet("low", "1–18", "1:1", 2, LOW_POCKETS),
  high: namedBet("high", "19–36", "1:1", 2, HIGH_POCKETS),
  dozen1: namedBet("dozen1", "1–12", "2:1", 3, DOZEN1_POCKETS),
  dozen2: namedBet("dozen2", "13–24", "2:1", 3, DOZEN2_POCKETS),
  dozen3: namedBet("dozen3", "25–36", "2:1", 3, DOZEN3_POCKETS),
  col1: namedBet("col1", "Колонка 1", "2:1", 3, COL1_POCKETS),
  col2: namedBet("col2", "Колонка 2", "2:1", 3, COL2_POCKETS),
  col3: namedBet("col3", "Колонка 3", "2:1", 3, COL3_POCKETS),
};

export const ROULETTE_COLOR_KEYS: readonly RouletteOutsideBet[] = ["red", "black", "zero"];
export const ROULETTE_EVEN_MONEY_KEYS: readonly RouletteOutsideBet[] = ["even", "odd", "low", "high"];
export const ROULETTE_DOZEN_KEYS: readonly RouletteOutsideBet[] = ["dozen1", "dozen2", "dozen3"];
export const ROULETTE_COLUMN_KEYS: readonly RouletteOutsideBet[] = ["col1", "col2", "col3"];
export const ROULETTE_BET_KEYS: readonly RouletteOutsideBet[] = [
  ...ROULETTE_COLOR_KEYS,
  ...ROULETTE_EVEN_MONEY_KEYS,
  ...ROULETTE_DOZEN_KEYS,
  ...ROULETTE_COLUMN_KEYS,
];
export const DEFAULT_ROULETTE_BET: RouletteBetKey = "red";

const ROULETTE_BET_ALIASES: Record<string, RouletteOutsideBet> = {
  красное: "red",
  красн: "red",
  черное: "black",
  чёрное: "black",
  зеро: "zero",
  чет: "even",
  четное: "even",
  чётное: "even",
  нечет: "odd",
  нечетное: "odd",
  нечётное: "odd",
  "1-18": "low",
  мало: "low",
  "19-36": "high",
  много: "high",
  "1rd": "dozen1",
  "1-12": "dozen1",
  "2rd": "dozen2",
  "13-24": "dozen2",
  "3rd": "dozen3",
  "25-36": "dozen3",
  "1col": "col1",
  "2col": "col2",
  "3col": "col3",
};

export function resolveRouletteBetKey(bet: unknown): string {
  const raw = String(bet ?? "").trim().toLowerCase().replaceAll("ё", "е");
  return ROULETTE_BET_ALIASES[raw] ?? ROULETTE_BET_ALIASES[String(bet ?? "").trim().toLowerCase()] ?? raw;
}

/** Quick stake chips in ₽. Clamped to the live quote bounds before use. */
export const ROULETTE_QUICK_STAKES: readonly number[] = [10, 25, 50, 100, 250, 500];

/** Table mode: pick a chip, click a felt spot. Repeat click stacks. */
export const ROULETTE_TABLE_CHIPS: readonly number[] = [10, 25, 50, 100, 250, 500];

/** One click on − / + in the stake stepper. Matches the house minimum. */
export const ROULETTE_STAKE_STEP = 10;

/** House 1×1: skip the wheel animation so the next spin can start right after the API. */
export const ROULETTE_FAST_PLAY_KEY = "focuspay_casino_roulette_fast";

type FastPlayStore = Pick<Storage, "getItem" | "setItem">;

function defaultFastPlayStore(): FastPlayStore | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readRouletteFastPlay(storage?: FastPlayStore | null): boolean {
  try {
    const store = storage === undefined ? defaultFastPlayStore() : storage;
    if (!store) return false;
    return store.getItem(ROULETTE_FAST_PLAY_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeRouletteFastPlay(on: boolean, storage?: FastPlayStore | null): void {
  try {
    const store = storage === undefined ? defaultFastPlayStore() : storage;
    if (!store) return;
    store.setItem(ROULETTE_FAST_PLAY_KEY, on ? "1" : "0");
  } catch {
    /* private mode / quota */
  }
}

export type RouletteUiPhase =
  | "idle"
  | "ready"
  | "spinning"
  | "win"
  | "loss"
  | "insufficient"
  | "invalid";

/**
 * What the table should show right now. Spinning wins over a leftover result.
 * Invalid / empty-wallet beat ready so the spin button and copy stay in sync.
 */
export function rouletteUiPhase(input: {
  spinning: boolean;
  stake: number;
  wallet: number | null;
  boundError?: string | null;
  result: { won: boolean } | null;
  authed: boolean;
}): RouletteUiPhase {
  if (input.spinning) return "spinning";
  if (!Number.isFinite(input.stake) || input.stake <= 0) return "invalid";
  if (input.wallet != null && Number.isFinite(input.wallet) && input.stake > input.wallet) {
    return "insufficient";
  }
  if (input.boundError) return "invalid";
  if (input.result) return input.result.won ? "win" : "loss";
  return input.authed ? "ready" : "idle";
}

/**
 * Visible wallet during a spin. `live` may already be the settled server
 * value; keep showing `frozen` until the wheel parks.
 */
export function visibleCasinoWallet(
  live: number | null,
  frozen: number | null,
  spinning: boolean,
): number | null {
  if (spinning && frozen != null) return frozen;
  return live;
}

export function isRouletteColorBet(value: unknown): value is "red" | "black" {
  return value === "red" || value === "black";
}

export function isRouletteOutsideBet(value: unknown): value is RouletteOutsideBet {
  const key = resolveRouletteBetKey(value);
  return Object.prototype.hasOwnProperty.call(ROULETTE_BETS, key);
}

function parseCoverPockets(value: string): number[] | null {
  const tokens = value
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (!tokens.length) return null;
  const pockets: number[] = [];
  const seen = new Set<number>();
  for (const token of tokens) {
    if (!/^(0|[1-9]\d?)$/.test(token)) return null;
    const pocket = Number(token);
    if (!Number.isInteger(pocket) || pocket < 0 || pocket >= ROULETTE_POCKET_COUNT) return null;
    if (seen.has(pocket)) continue;
    seen.add(pocket);
    pockets.push(pocket);
  }
  if (!pockets.length || pockets.length > ROULETTE_MAX_COVER) return null;
  return pockets.sort((a, b) => a - b);
}

export function isRouletteBetKey(value: unknown): value is RouletteBetKey {
  if (typeof value === "number") {
    return Number.isInteger(value) && value >= 0 && value < ROULETTE_POCKET_COUNT;
  }
  if (typeof value !== "string" && typeof value !== "number") return false;
  const key = resolveRouletteBetKey(value);
  if (isRouletteOutsideBet(key)) return true;
  return parseCoverPockets(key) != null;
}

export function canonicalRouletteBetKey(pockets: readonly number[]): RouletteBetKey {
  const unique = [...new Set(pockets.map((pocket) => Number(pocket)))].sort((a, b) => a - b);
  if (unique.length === 1 && unique[0] === 0) return "zero";
  if (unique.length === 1) return String(unique[0]);
  return unique.join(",");
}

export function rouletteCoverWord(cover: number): string {
  const n100 = cover % 100;
  if (n100 >= 11 && n100 <= 14) return "чисел";
  const last = cover % 10;
  if (last === 1) return "число";
  if (last === 2 || last === 3 || last === 4) return "числа";
  return "чисел";
}

export function rouletteOddsLabel(cover: number): string {
  const profit = (ROULETTE_STRAIGHT_RETURN - cover) / cover;
  if (Number.isInteger(profit)) return `${profit}:1`;
  const rounded = Math.round(profit * 100) / 100;
  return `${String(rounded).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "")}:1`;
}

export function rouletteCoverTitle(pockets: readonly number[]): string {
  if (pockets.length === 1) return pockets[0] === 0 ? "Зеро" : String(pockets[0]);
  if (pockets.length <= 6) return pockets.join(", ");
  return `${pockets.length} ${rouletteCoverWord(pockets.length)}`;
}

function coverSpec(pockets: number[]): RouletteBetSpec {
  for (const named of Object.values(ROULETTE_BETS)) {
    if (named.pockets.length === pockets.length && named.pockets.every((pocket, index) => pocket === pockets[index])) {
      return named;
    }
  }
  const cover = pockets.length;
  const multiplier = ROULETTE_STRAIGHT_RETURN / cover;
  const key = canonicalRouletteBetKey(pockets);
  const title = rouletteCoverTitle(pockets);
  const odds = rouletteOddsLabel(cover);
  return {
    key,
    title,
    ariaLabel: `Ставка на ${title}, выплата ${odds.replace(":", " к ")}`,
    odds,
    payoutMultiplier: multiplier,
    profitRatio: multiplier - 1,
    pockets,
  };
}

function straightSpec(pocket: number): RouletteBetSpec {
  return coverSpec([pocket]);
}

export function rouletteBetSpec(bet: unknown): RouletteBetSpec {
  if (typeof bet === "number" && Number.isInteger(bet) && bet >= 0 && bet < ROULETTE_POCKET_COUNT) {
    return straightSpec(bet);
  }
  const key = resolveRouletteBetKey(bet);
  if (isRouletteOutsideBet(key)) return ROULETTE_BETS[key];
  const pockets = parseCoverPockets(key);
  if (pockets) return coverSpec(pockets);
  return ROULETTE_BETS.red;
}

/** Even-money (red/black) vs a 1-pocket ×36 spot. Table snapshot carries both caps. */
export function rouletteTableSpotMax(bet: string, maxEven: number, maxStraight: number): number {
  return rouletteBetSpec(bet).payoutMultiplier >= ROULETTE_STRAIGHT_RETURN ? maxStraight : maxEven;
}

export function toggleRoulettePocket(current: RouletteBetKey, pocket: number): RouletteBetKey {
  if (!Number.isInteger(pocket) || pocket < 0 || pocket >= ROULETTE_POCKET_COUNT) {
    return current;
  }
  if (isRouletteColorBet(current)) {
    return canonicalRouletteBetKey([pocket]);
  }
  const spec = rouletteBetSpec(current);
  const next = new Set(spec.pockets);
  if (next.has(pocket)) {
    if (next.size === 1) return canonicalRouletteBetKey([...next]);
    next.delete(pocket);
  } else {
    if (next.size >= ROULETTE_MAX_COVER) return current;
    next.add(pocket);
  }
  return canonicalRouletteBetKey([...next]);
}

export function isRoulettePocket(value: unknown): boolean {
  const pocket = Number(value);
  return Number.isInteger(pocket) && pocket >= 0 && pocket < ROULETTE_POCKET_COUNT;
}

export function roulettePocketColor(pocket: number): RoulettePocketColor {
  if (pocket === 0) return "green";
  return RED_POCKETS.has(pocket) ? "red" : "black";
}

export function rouletteWheelIndex(pocket: number): number {
  return WHEEL_INDEX.get(pocket) ?? 0;
}

export function rouletteColorLabel(color: RoulettePocketColor): string {
  if (color === "green") return "зеро";
  return color === "red" ? "красное" : "чёрное";
}

export function rouletteBetWins(bet: RouletteBetKey, pocket: number): boolean {
  return rouletteBetSpec(bet).pockets.includes(pocket);
}

export function rouletteBetFromPocket(pocket: number): RouletteBetKey {
  return canonicalRouletteBetKey([pocket]);
}

export function rouletteStraightKey(pocket: number): RouletteBetKey {
  if (pocket === 0) return "zero";
  return canonicalRouletteBetKey([pocket]);
}

export function rouletteSelectedPockets(bet: RouletteBetKey): number[] {
  if (isRouletteColorBet(bet)) return [];
  return [...rouletteBetSpec(bet).pockets];
}

export function rouletteSelectedPocket(bet: RouletteBetKey): number | null {
  const pockets = rouletteSelectedPockets(bet);
  return pockets.length === 1 ? pockets[0] : null;
}

/** Degrees per pocket on the wheel. */
export const ROULETTE_SECTOR_DEG = 360 / ROULETTE_POCKET_COUNT;

/**
 * Next absolute wheel rotation that parks `pocket` under the pointer at 12 o'clock.
 * Always turns forward from `currentDeg` by at least `turns` full revolutions, so a
 * run of spins keeps rotating the same way and the landing sector stays exact.
 */
export function rouletteRotationFor(pocket: number, currentDeg: number, turns = 4): number {
  const target = -rouletteWheelIndex(pocket) * ROULETTE_SECTOR_DEG;
  const base = currentDeg + turns * 360;
  const delta = ((target - base) % 360 + 360) % 360;
  return base + delta;
}

/**
 * While the server draws, the rotor coasts in rAF (no CSS transition).
 * ~2.4 rev/s; the settle interrupt continues from this speed, one motion.
 */
export const ROULETTE_COAST_DEG_PER_MS = 0.85;

/** Classic European felt: 0 spanning the left, then 12 columns of 3 / 2 / 1. */
export const ROULETTE_FELT_ORDER: readonly number[] = [
  0,
  ...Array.from({ length: 12 }, (_, col) => {
    const base = col * 3;
    return [base + 3, base + 2, base + 1];
  }).flat(),
];

export const ROULETTE_SPIN_EASINGS = [
  "cubic-bezier(0.12, 0.82, 0.02, 1)",
  "cubic-bezier(0.07, 0.68, 0.04, 1)",
  "cubic-bezier(0.16, 0.62, 0.08, 1)",
  "cubic-bezier(0.05, 0.9, 0.06, 1)",
] as const;

export interface RouletteSpinPlan {
  turns: number;
  durationMs: number;
  easing: string;
}

function cryptoInt(maxExclusive: number): number {
  if (maxExclusive <= 1) return 0;
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] % maxExclusive;
}

/** Fresh spin: 6–10 extra turns, 3.8–6.2s, one of a few decelerations. Not Math.random. */
export function makeRouletteSpinPlan(reducedMotion = false): RouletteSpinPlan {
  if (reducedMotion) return { turns: 0, durationMs: 0, easing: "linear" };
  return {
    turns: 6 + cryptoInt(5),
    durationMs: 3800 + cryptoInt(2401),
    easing: ROULETTE_SPIN_EASINGS[cryptoInt(ROULETTE_SPIN_EASINGS.length)],
  };
}

export interface RouletteSpinRecord {
  id: string;
  pocket: number;
  color: RoulettePocketColor;
  bet?: RouletteBetKey;
  won?: boolean;
}

/**
 * Shared table closer publishes `spin` and `settled` in the same shot
 * (`locked_at` == `settled_at`). The wheel must keep going until it parks;
 * treating `settled` as "stop now" skips the 4–6s spin.
 */
export function rouletteTableRevealReady(tableSpinning: boolean, wheelParked: boolean): boolean {
  if (!tableSpinning) return true;
  return wheelParked;
}

/** Place chips only while the shared round is collecting. Settled is the last spin, not a lock. */
export function rouletteTableAcceptsBets(status: string | null | undefined): boolean {
  return status == null || status === "open" || status === "settled";
}

/** Poll/GET recovery: a locked/spinning/settled snapshot with a pocket should start the same spin as SSE. */
export function rouletteTableShouldSpinFromSnapshot(
  snap: { round_id?: string; status?: string; pocket?: number | null },
  alreadySpunRound: string | null,
): boolean {
  if (!snap.round_id || snap.round_id === alreadySpunRound) return false;
  if (snap.status === "open" || !snap.status) return false;
  return isRoulettePocket(snap.pocket);
}

export const ROULETTE_HISTORY_LIMIT = 10;

/** Newest first, deduped by round id, capped at the history limit. */
export function mergeRouletteHistory(
  current: readonly RouletteSpinRecord[],
  incoming: readonly RouletteSpinRecord[],
): RouletteSpinRecord[] {
  const seen = new Set<string>();
  const out: RouletteSpinRecord[] = [];
  for (const row of [...incoming, ...current]) {
    if (!row.id || seen.has(row.id)) continue;
    seen.add(row.id);
    out.push(row);
    if (out.length >= ROULETTE_HISTORY_LIMIT) break;
  }
  return out;
}

/** Drop the in-flight round so the tape above the wheel cannot spoiler the pocket. */
export function rouletteHistoryWithoutRound(
  rows: readonly RouletteSpinRecord[],
  roundId: string | null | undefined,
): RouletteSpinRecord[] {
  if (!roundId) return [...rows];
  return rows.filter((row) => row.id !== roundId);
}

/** Hub / landed highlight: the server pocket is known while spinning, but must stay hidden. */
export function rouletteVisiblePocket(spinning: boolean, pocket: number | null | undefined): number | null {
  if (spinning || pocket == null || !isRoulettePocket(pocket)) return null;
  return Number(pocket);
}

/** Max chips in one confirm payload. Mirrors backend ROULETTE_TABLE_CHIPS_MAX. */
export const ROULETTE_TABLE_DRAFT_MAX = 80;

export const ROULETTE_LAST_TABLE_BETS_KEY = "focuspay_casino_roulette_last_table_bets";

export type RouletteDraftChip = {
  bet: RouletteBetKey;
  amount: number;
};

function moneyRub(value: number): number {
  return Math.round(value * 100) / 100;
}

export function pushRouletteDraftChip(
  draft: readonly RouletteDraftChip[],
  bet: RouletteBetKey,
  amount: number,
): RouletteDraftChip[] {
  if (!Number.isFinite(amount) || amount <= 0) return [...draft];
  if (draft.length >= ROULETTE_TABLE_DRAFT_MAX) return [...draft];
  return [...draft, { bet, amount: moneyRub(amount) }];
}

export function undoRouletteDraftChip(draft: readonly RouletteDraftChip[]): RouletteDraftChip[] {
  if (!draft.length) return [];
  return draft.slice(0, -1);
}

export function clearRouletteDraftSpot(
  draft: readonly RouletteDraftChip[],
  bet: RouletteBetKey,
): RouletteDraftChip[] {
  return draft.filter((chip) => chip.bet !== bet);
}

export function rouletteDraftTotal(draft: readonly RouletteDraftChip[]): number {
  return moneyRub(draft.reduce((sum, chip) => sum + (Number(chip.amount) || 0), 0));
}

export function mergeRouletteDraftBySpot(draft: readonly RouletteDraftChip[]): RouletteDraftChip[] {
  const totals = new Map<string, number>();
  const order: string[] = [];
  for (const chip of draft) {
    const key = String(chip.bet);
    if (!totals.has(key)) order.push(key);
    totals.set(key, (totals.get(key) || 0) + (Number(chip.amount) || 0));
  }
  return order.map((bet) => ({ bet, amount: moneyRub(totals.get(bet) || 0) }));
}

export function rouletteDraftConfirmPayload(
  draft: readonly RouletteDraftChip[],
): Array<{ bet: string; amount_rub: number }> {
  return mergeRouletteDraftBySpot(draft)
    .filter((chip) => chip.amount > 0)
    .map((chip) => ({ bet: String(chip.bet), amount_rub: chip.amount }));
}

/** Pop the last chip. Remainder is what stays on that spot after the pop (API clears the whole spot). */
export function rouletteUndoLastPlace(log: readonly RouletteDraftChip[]): {
  next: RouletteDraftChip[];
  bet: RouletteBetKey;
  remainder: number;
  removed: number;
} | null {
  if (!log.length) return null;
  const last = log[log.length - 1];
  const next = log.slice(0, -1);
  const remainder = rouletteDraftTotal(next.filter((chip) => chip.bet === last.bet));
  return { next, bet: last.bet, remainder, removed: last.amount };
}

/**
 * Id the roulette table stores on a bet. `/auth/me` puts the Telegram id in
 * `telegram_user_id`; `id` is the web_users row and never matches a seat.
 * Web-only accounts are the negative `client_user_id`. `my_bets` is already
 * filtered to the viewer, so its user id is the fallback when /me omits it.
 */
export function casinoViewerId(
  user:
    | { id?: unknown; telegram_user_id?: unknown; telegram_id?: unknown; client_user_id?: unknown }
    | null
    | undefined,
  myBets?: readonly { user_id?: number }[] | null,
): number | null {
  for (const raw of [user?.telegram_user_id, user?.telegram_id, user?.client_user_id]) {
    const id = Number(raw);
    if (Number.isFinite(id) && id !== 0) return id;
  }
  for (const row of myBets || []) {
    const id = Number(row.user_id);
    if (Number.isFinite(id) && id !== 0) return id;
  }
  return null;
}

export function lastTableBetsToDraft(
  rows: readonly { bet?: string; stake_rub?: number }[],
): RouletteDraftChip[] {
  const out: RouletteDraftChip[] = [];
  for (const row of rows) {
    if (!isRouletteBetKey(row.bet)) continue;
    const amount = Number(row.stake_rub);
    if (!Number.isFinite(amount) || amount <= 0) continue;
    out.push({ bet: row.bet, amount: moneyRub(amount) });
  }
  return out;
}

type LastBetsStore = Pick<Storage, "getItem" | "setItem">;

function defaultSessionStore(): LastBetsStore | null {
  try {
    if (typeof window === "undefined") return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function readRouletteLastTableBets(storage?: LastBetsStore | null): RouletteDraftChip[] {
  try {
    const store = storage === undefined ? defaultSessionStore() : storage;
    if (!store) return [];
    const raw = store.getItem(ROULETTE_LAST_TABLE_BETS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return lastTableBetsToDraft(
      parsed.map((row) => {
        if (!row || typeof row !== "object") return {};
        const item = row as { bet?: unknown; amount?: unknown; stake_rub?: unknown };
        return {
          bet: typeof item.bet === "string" ? item.bet : undefined,
          stake_rub: Number(item.amount ?? item.stake_rub),
        };
      }),
    );
  } catch {
    return [];
  }
}

export function writeRouletteLastTableBets(
  chips: readonly RouletteDraftChip[],
  storage?: LastBetsStore | null,
): void {
  try {
    const store = storage === undefined ? defaultSessionStore() : storage;
    if (!store) return;
    const rows = lastTableBetsToDraft(chips.map((chip) => ({ bet: String(chip.bet), stake_rub: chip.amount })));
    if (!rows.length) {
      store.setItem(ROULETTE_LAST_TABLE_BETS_KEY, "[]");
      return;
    }
    store.setItem(ROULETTE_LAST_TABLE_BETS_KEY, JSON.stringify(rows));
  } catch {
    /* private mode / quota */
  }
}
