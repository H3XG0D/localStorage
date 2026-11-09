import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { ApiError, apiErrorTableId, API_BASE, getToken } from "@/lib/api";
import {
  getCasinoBlackjackPending,
  getCasinoFairnessSession,
  getCasinoHouseTable,
  getCasinoPlayQuote,
  getCasinoPlayTape,
  getCasinoRouletteTable,
  getPublicCasinoRouletteTable,
  createCasinoHouseTable,
  leaveCasinoHouseTable,
  resolveCasinoHouseTable,
  playCasinoBlackjackAction,
  playCasinoHouseRound,
  postCasinoRouletteTableBet,
  postCasinoRouletteTableBets,
  postCasinoRouletteTableClear,
  rotateCasinoFairnessSession,
  setCasinoFairnessClientSeed,
  type CasinoFairnessSession,
  type CasinoHouseTableSnapshot,
  type CasinoPlayQuote,
  type CasinoPlayResult,
  type CasinoRouletteTableSnapshot,
  type CasinoTapeRow,
} from "@/lib/public";
import {
  DEFAULT_ROULETTE_BET,
  ROULETTE_QUICK_STAKES,
  ROULETTE_TABLE_CHIPS,
  ROULETTE_STAKE_STEP,
  ROULETTE_TABLE_DRAFT_MAX,
  isRoulettePocket,
  casinoViewerId,
  isRouletteBetKey,
  lastTableBetsToDraft,
  mergeRouletteDraftBySpot,
  makeRouletteSpinPlan,
  mergeRouletteHistory,
  rouletteHistoryWithoutRound,
  readRouletteFastPlay,
  readRouletteLastTableBets,
  rouletteBetSpec,
  rouletteDraftConfirmPayload,
  rouletteDraftTotal,
  roulettePocketColor,
  rouletteTableRevealReady,
  rouletteTableAcceptsBets,
  rouletteTableShouldSpinFromSnapshot,
  rouletteTableSpotMax,
  rouletteUiPhase,
  rouletteUndoLastPlace,
  visibleCasinoWallet,
  writeRouletteFastPlay,
  writeRouletteLastTableBets,
  type RouletteBetKey,
  type RouletteDraftChip,
  type RouletteSpinPlan,
  type RouletteSpinRecord,
} from "./roulette";
import { CasinoRoulette, type CasinoRouletteResult } from "./CasinoRoulette";
import { useSession } from "@/lib/session";
import {
  CASINO_BALANCE_EVENT,
  CASINO_BALANCE_HOLD_EVENT,
  CASINO_BALANCE_RELEASE_EVENT,
  HEAD_TO_HEAD_IDS,
  catalogGame,
  canonicalGameId,
  pushRecent,
} from "./gameCatalog";
import { getBalance } from "@/lib/user";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { asDiePips, CasinoDiceDuel, prefersCasinoReducedMotion } from "./CasinoDice";
import { CasinoHouseCards } from "./CasinoHouseCards";
import { cardsFromPlayResult, houseCardsRevealMs } from "./houseCards";
import { CasinoHouseTables } from "./CasinoHouseTables";
import { CasinoJackpot } from "./CasinoJackpot";
import { CasinoRaffle } from "./CasinoRaffle";
import { CasinoFixedRooms } from "./CasinoFixedRooms";
import { CasinoClanWars } from "./CasinoClanWars";
import { CasinoModeSwitch, type CasinoPlayMode } from "./CasinoModeSwitch";
import { CasinoPlayersLobby } from "./CasinoPlayersLobby";
import { CasinoPoker } from "./CasinoPoker";
import { CasinoNardy } from "./CasinoNardy";
import { CasinoDraughts } from "./CasinoDraughts";
import { haptic, setHapticMuted } from "./telegram";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function clampStake(raw: string, min: number, max: number): number {
  const parsed = Number(raw.replace(",", "."));
  if (!Number.isFinite(parsed) || parsed <= 0) return min;
  return Math.min(max, Math.max(min, Math.round(parsed * 100) / 100));
}

function walletCap(maxBet: number, walletRub: number | null): number {
  if (walletRub == null || !Number.isFinite(walletRub)) return maxBet;
  return Math.min(maxBet, Math.max(0, Math.round(walletRub * 100) / 100));
}

function tableSpotCaps(snap: CasinoRouletteTableSnapshot | null): { even: number; straight: number } {
  const even = snap?.max_even_bet_rub ?? snap?.max_bet_rub ?? 100000;
  return { even, straight: snap?.max_straight_bet_rub ?? even };
}

type TableLiveChip = RouletteDraftChip & { localId: number };

function dropLiveChip(log: readonly TableLiveChip[], localId: number): TableLiveChip[] {
  return log.filter((chip) => chip.localId !== localId);
}

function liveChipLog(log: readonly TableLiveChip[]): RouletteDraftChip[] {
  return log.map((chip) => ({ bet: chip.bet, amount: chip.amount }));
}

/** ×2 never goes above the wallet: extra is all-in, still capped by house max. */
function doubleOrAllIn(current: number, min: number, maxBet: number, walletRub: number | null): number {
  const doubled = Math.round(current * 2 * 100) / 100;
  const cap = walletCap(maxBet, walletRub);
  if (doubled > cap) return cap;
  return clampStake(String(doubled), min, cap);
}

function rollDurationMs(pace: "manual" | "auto"): number {
  if (prefersCasinoReducedMotion()) return 0;
  return pace === "auto" ? 450 : 1000;
}

function pipsOf(result: CasinoPlayResult | null, side: "player" | "house"): number | null {
  if (!result) return null;
  const top = side === "player" ? result.player_pips : result.house_pips;
  const nested = side === "player" ? result.rng?.player_pips : result.rng?.house_pips;
  return asDiePips(top ?? nested ?? null);
}

function isHeadToHead(id: string): boolean {
  return (HEAD_TO_HEAD_IDS as readonly string[]).includes(id);
}

function isShellGame(id: string): boolean {
  return id === "holdem" || id === "jackpot" || id === "raffle" || id === "fixed_room" || id === "clan_war" || id === "nardy" || id === "russian_draughts";
}

function defaultPlayMode(id: string): CasinoPlayMode {
  if (id === "raffle") return "house";
  return "players";
}

/** Roulette pocket of a finished round, wherever the payload carried it. */
function pocketOf(result: CasinoPlayResult | null): number | null {
  if (!result) return null;
  const raw = result.pocket ?? result.outcome?.pocket ?? result.rng?.pocket;
  return isRoulettePocket(raw) ? Number(raw) : null;
}

function spinRecordOf(result: CasinoPlayResult): RouletteSpinRecord | null {
  const pocket = pocketOf(result);
  if (pocket == null) return null;
  return {
    id: String(result.game_id || ""),
    pocket,
    color: roulettePocketColor(pocket),
    bet: isRouletteBetKey(result.bet) ? result.bet : undefined,
    won: result.outcome?.kind === "win",
  };
}

function tableSnapWithPocket(
  live: CasinoRouletteTableSnapshot | null,
  roundId: string,
  pocket: number,
  status: string,
  commit?: string,
): CasinoRouletteTableSnapshot {
  const base = live ?? {
    success: true,
    round_id: roundId,
    status,
    commit_hash: commit || "",
    server_seed: null,
    closes_at: null,
    pocket,
    color: null,
    wheel_index: null,
    player_count: 0,
    max_players: 24,
    collect_seconds: 25,
    min_bet_rub: 10,
    max_bet_rub: 100000,
    max_even_bet_rub: 100000,
    max_straight_bet_rub: 100000,
    enabled: true,
    algorithm: "hmac-sha256-pocket-mod37",
    modulus: 37,
    client_seed: "focuspay",
    nonce: 0,
    hmac_message: null,
    players: [],
    history: [],
    my_bet: null,
    my_stake_rub: 0,
  };
  return {
    ...base,
    round_id: roundId,
    status,
    pocket,
    commit_hash: commit || base.commit_hash,
  };
}

function tapeSpinRecords(rows: readonly CasinoTapeRow[]): RouletteSpinRecord[] {
  const out: RouletteSpinRecord[] = [];
  for (const row of rows) {
    const pocket = row.result?.pocket;
    if (!isRoulettePocket(pocket)) continue;
    out.push({
      id: row.game_id,
      pocket: Number(pocket),
      color: roulettePocketColor(Number(pocket)),
      bet: isRouletteBetKey(row.result?.bet) ? row.result?.bet : undefined,
      won: row.won,
    });
  }
  return out;
}

function PlayNote({ title, children }: { title: string; children: string }) {
  return (
    <section className="casino-play-canvas casino-play-stub" data-casino-play-note="">
      <h1>{title}</h1>
      <p className="casino-muted">{children}</p>
    </section>
  );
}

export function CasinoPlay() {
  const { gameId: rawGameId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthed, user } = useSession();
  const gameId = canonicalGameId(rawGameId || "");
  const game = catalogGame(gameId);
  const defaultMode = defaultPlayMode(gameId);
  const modeParam = params.get("mode");
  const mode: CasinoPlayMode =
    gameId === "roulette" || isHeadToHead(gameId)
      ? "players"
      : modeParam === "house" || modeParam === "players"
        ? modeParam
        : defaultMode;
  const isCub = mode === "house" && gameId === "pvp_dice";
  const tableIdParam = (params.get("ht") || "").trim();
  const houseTableView = isCub && (params.get("view") === "table" || Boolean(tableIdParam));
  const isCardHouse = mode === "house" && (gameId === "baccara" || gameId === "blackjack");
  const isBlackjackHouse = isCardHouse && gameId === "blackjack";
  const isRouletteHouse = mode === "house" && gameId === "roulette";
  const isRouletteTable = mode === "players" && gameId === "roulette";
  const isRoulette = isRouletteHouse || isRouletteTable;
  const isHousePlay = isCub || isCardHouse || isRouletteHouse || isRouletteTable;
  const houseGameType = isCub ? "cub" : gameId;
  const showPlayers = mode === "players" && isHeadToHead(gameId);
  const showHouseTable = houseTableView;
  const shell = isShellGame(gameId);
  const gameTitle = game ? `${game.emoji} ${game.name}` : gameId;

  useEffect(() => {
    if (rawGameId === "cub") {
      navigate(casinoTo("/casino/play/pvp_dice?mode=players"), { replace: true });
    }
  }, [rawGameId, navigate]);

  useEffect(() => {
    const forcePlayers = gameId === "roulette" || gameId === "fixed_room" || gameId === "jackpot" || gameId === "nardy" || gameId === "russian_draughts" || isHeadToHead(gameId);
    if (!forcePlayers || modeParam !== "house") return;
    const nextParams = new URLSearchParams(params);
    nextParams.set("mode", "players");
    nextParams.delete("view");
    nextParams.delete("ht");
    setParams(nextParams, { replace: true });
  }, [gameId, modeParam, params, setParams]);

  useEffect(() => {
    if (game) pushRecent(game.id);
  }, [game]);

  const [tab, setTab] = useState<"manual" | "auto">("manual");
  const [stake, setStake] = useState("100");
  const [quote, setQuote] = useState<CasinoPlayQuote | null>(null);
  const [pending, setPending] = useState(false);
  const [acting, setActing] = useState(false);
  const [last, setLast] = useState<CasinoPlayResult | null>(null);
  const [rolling, setRolling] = useState(false);
  const [tapeTab, setTapeTab] = useState<"mine" | "all" | "high">("all");
  const [tape, setTape] = useState<CasinoTapeRow[]>([]);
  const [fairOpen, setFairOpen] = useState(false);
  const [session, setSession] = useState<CasinoFairnessSession | null>(null);
  const [clientSeed, setClientSeed] = useState("");
  const autoStop = useRef(false);
  const [autoCount, setAutoCount] = useState("10");
  const [onWin, setOnWin] = useState<"reset" | "increase">("reset");
  const [onLose, setOnLose] = useState<"reset" | "increase">("reset");
  const [onWinPct, setOnWinPct] = useState("50");
  const [onLosePct, setOnLosePct] = useState("50");
  const [stopProfit, setStopProfit] = useState("0");
  const [stopLoss, setStopLoss] = useState("0");
  const [walletRub, setWalletRub] = useState<number | null>(null);
  const [frozenWallet, setFrozenWallet] = useState<number | null>(null);
  const [houseBots, setHouseBots] = useState(3);
  const [houseSnap, setHouseSnap] = useState<CasinoHouseTableSnapshot | null>(null);
  const houseSnapRef = useRef<CasinoHouseTableSnapshot | null>(null);
  houseSnapRef.current = houseSnap;
  const [rouletteBet, setRouletteBet] = useState<RouletteBetKey>(DEFAULT_ROULETTE_BET);
  const [spinning, setSpinning] = useState(false);
  const [spinPlan, setSpinPlan] = useState<RouletteSpinPlan | null>(null);
  const [spins, setSpins] = useState<RouletteSpinRecord[]>([]);
  const [tableSnap, setTableSnap] = useState<CasinoRouletteTableSnapshot | null>(null);
  const mineId = casinoViewerId(user, tableSnap?.my_bets);
  const [fastPlay, setFastPlay] = useState(() => readRouletteFastPlay());
  const [placeLog, setPlaceLog] = useState<TableLiveChip[]>([]);
  const [optimisticChips, setOptimisticChips] = useState<TableLiveChip[]>([]);
  const [placingCount, setPlacingCount] = useState(0);
  const [tableBusy, setTableBusy] = useState(false);
  const [lastTableBets, setLastTableBets] = useState<RouletteDraftChip[]>(() => readRouletteLastTableBets());
  const clampOnBetSwitch = useRef(false);

  useEffect(() => {
    setLast(null);
    setRolling(false);
    setActing(false);
    setSpinning(false);
    setSpinPlan(null);
    setFrozenWallet(null);
    if (walletHoldRef.current) {
      walletHoldRef.current = false;
      revealOnceRef.current = true;
      window.dispatchEvent(new Event(CASINO_BALANCE_RELEASE_EVENT));
    }
    if (!houseTableView) setHouseSnap(null);
    setTableSnap(null);
    setPlaceLog([]);
    setOptimisticChips([]);
    setPlacingCount(0);
    setTableBusy(false);
    tableRoundRef.current = null;
    tableSpinningRef.current = false;
    tableSpunRound.current = null;
    wheelParkedRef.current = false;
    tableSettleOptionalRef.current = false;
    pendingTableSettle.current = null;
    tableSnapRef.current = null;
  }, [gameId, mode, houseTableView]);

  useEffect(() => {
    if (isBlackjackHouse || houseTableView || isRoulette) setTab("manual");
  }, [isBlackjackHouse, houseTableView, isRoulette]);

  /** Seed the wheel history from finished rounds so a refresh keeps the last pockets. */
  useEffect(() => {
    if (!isRouletteHouse) {
      if (!isRouletteTable) setSpins([]);
      return undefined;
    }
    let cancelled = false;
    getCasinoPlayTape("all", "roulette")
      .then((payload) => {
        if (!cancelled) setSpins(mergeRouletteHistory([], tapeSpinRecords(payload.rows || [])));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isRouletteHouse, isRouletteTable]);

  useEffect(() => {
    if (!isAuthed || !isBlackjackHouse) return;
    let cancelled = false;
    getCasinoBlackjackPending()
      .then((payload) => {
        if (cancelled || !payload.pending) return;
        setLast(payload.pending);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isAuthed, isBlackjackHouse]);

  useEffect(() => {
    if (!houseTableView || !tableIdParam) return undefined;
    let cancelled = false;
    getCasinoHouseTable(tableIdParam)
      .then((row) => {
        if (!cancelled) setHouseSnap(row);
      })
      .catch(() => {
        if (!cancelled) setHouseSnap(null);
      });
    return () => {
      cancelled = true;
    };
  }, [houseTableView, tableIdParam]);

  const stakeNumber = Number(stake.replace(",", ".")) || 0;
  const tableSpinningRef = useRef(false);
  const tableSpunRound = useRef<string | null>(null);
  const wheelParkedRef = useRef(false);
  const tableSettleOptionalRef = useRef(false);
  const startTableSpinRef = useRef<(snap: CasinoRouletteTableSnapshot) => void>(() => undefined);
  const pendingTableSettle = useRef<{
    stake: number;
    payout: number;
    won: boolean;
    pocket: number;
    bet: RouletteBetKey;
    commit?: string;
    roundId: string;
  } | null>(null);
  const tableSnapRef = useRef<CasinoRouletteTableSnapshot | null>(null);
  const tableStakeAtSpin = useRef(0);
  const placeLogRef = useRef<TableLiveChip[]>([]);
  const tableRoundRef = useRef<string | null>(null);
  const tableQueueRef = useRef(Promise.resolve());
  const nextPlaceId = useRef(1);
  const mineIdRef = useRef(mineId);
  const stakeRef = useRef(stakeNumber);
  const walletRubRef = useRef(walletRub);
  const walletHoldRef = useRef(false);
  const revealOnceRef = useRef(true);
  const pendingHouseRef = useRef<CasinoPlayResult | null>(null);
  const cardRevealWaiterRef = useRef<(() => void) | null>(null);
  const holdWalletRef = useRef<() => void>(() => undefined);
  const revealRouletteRoundRef = useRef<() => void>(() => undefined);
  const tapeDelayRef = useRef(0);
  const fastPlayRef = useRef(false);
  mineIdRef.current = mineId;
  placeLogRef.current = placeLog;
  stakeRef.current = stakeNumber;
  walletRubRef.current = walletRub;
  fastPlayRef.current = fastPlay;

  useEffect(() => {
    return () => {
      window.clearTimeout(tapeDelayRef.current);
      if (walletHoldRef.current) {
        walletHoldRef.current = false;
        window.dispatchEvent(new Event(CASINO_BALANCE_RELEASE_EVENT));
      }
    };
  }, []);

  const refreshWallet = useCallback(() => {
    if (!isAuthed) {
      setWalletRub(null);
      return;
    }
    getBalance()
      .then((row) => {
        if (walletHoldRef.current) return;
        const available = Number(row.available_rub);
        const balance = Number(row.balance_rub);
        if (Number.isFinite(available) && available >= 0) setWalletRub(available);
        else if (Number.isFinite(balance) && balance >= 0) setWalletRub(balance);
        else setWalletRub(null);
      })
      .catch(() => undefined);
  }, [isAuthed]);

  useEffect(() => {
    if (!houseTableView || !tableIdParam || !houseSnap?.choice) return undefined;
    const timer = window.setInterval(() => {
      getCasinoHouseTable(tableIdParam)
        .then((row) => {
          const hadChoice = Boolean(houseSnapRef.current?.choice);
          setHouseSnap(row);
          if (hadChoice && !row.choice) refreshWallet();
        })
        .catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [houseTableView, tableIdParam, houseSnap?.choice, refreshWallet]);

  const applyTableSnap = useCallback((snap: CasinoRouletteTableSnapshot) => {
    if (tableSpinningRef.current) return;
    tableSnapRef.current = snap;
    setTableSnap(snap);
    const rows: RouletteSpinRecord[] = (snap.history || []).map((row) => ({
      id: row.id,
      pocket: row.pocket,
      color: roulettePocketColor(row.pocket),
    }));
    if (rows.length) setSpins(mergeRouletteHistory([], rows));
  }, []);

  const loadTable = useCallback(async () => {
    if (tableSpinningRef.current) return;
    try {
      const snap = isAuthed ? await getCasinoRouletteTable() : await getPublicCasinoRouletteTable();
      if (tableSpinningRef.current) return;
      if (rouletteTableShouldSpinFromSnapshot(snap, tableSpunRound.current)) {
        const rows: RouletteSpinRecord[] = (snap.history || []).map((row) => ({
          id: row.id,
          pocket: row.pocket,
          color: roulettePocketColor(row.pocket),
        }));
        const seeded = rouletteHistoryWithoutRound(rows, snap.round_id);
        if (seeded.length) setSpins(mergeRouletteHistory([], seeded));
        startTableSpinRef.current(snap);
        return;
      }
      applyTableSnap(snap);
    } catch {
      /* keep the last snapshot */
    }
  }, [applyTableSnap, isAuthed]);

  useEffect(() => {
    if (!isRouletteTable) return undefined;
    void loadTable();
    if (!isAuthed) {
      const poll = window.setInterval(() => {
        if (!tableSpinningRef.current) void loadTable();
      }, 4000);
      return () => window.clearInterval(poll);
    }
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/roulette-table/events${qs}`, { withCredentials: true });
      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            round_id?: string;
            pocket?: number;
            commit_hash?: string;
            results?: Array<{ user_id: number; bet: string; won: boolean; payout_rub: number }>;
          };
          if (payload.type === "bet" || payload.type === "idle") {
            if (!tableSpinningRef.current) void loadTable();
          }
          if (payload.type === "settled") {
            const viewer = mineIdRef.current;
            const mineRows = (payload.results || []).filter((row) => viewer != null && row.user_id === viewer);
            const pocket = isRoulettePocket(payload.pocket) ? Number(payload.pocket) : tableSnapRef.current?.pocket;
            if (mineRows.length && pocket != null && payload.round_id) {
              const payout = mineRows.reduce((sum, row) => sum + (Number(row.payout_rub) || 0), 0);
              const only = mineRows.length === 1 ? mineRows[0] : null;
              pendingTableSettle.current = {
                stake: tableStakeAtSpin.current || tableSnapRef.current?.my_stake_rub || 0,
                payout,
                won: payout > 0,
                pocket,
                bet: only && isRouletteBetKey(only.bet) ? only.bet : DEFAULT_ROULETTE_BET,
                commit: payload.commit_hash,
                roundId: payload.round_id,
              };
            }
            if (!tableSpinningRef.current && payload.round_id && isRoulettePocket(payload.pocket)) {
              startTableSpinRef.current(
                tableSnapWithPocket(
                  tableSnapRef.current,
                  payload.round_id,
                  Number(payload.pocket),
                  "settled",
                  payload.commit_hash,
                ),
              );
            }
            revealRouletteRoundRef.current();
          }
          if (payload.type === "spin" && isRoulettePocket(payload.pocket) && payload.round_id) {
            startTableSpinRef.current(
              tableSnapWithPocket(
                tableSnapRef.current,
                payload.round_id,
                Number(payload.pocket),
                "spinning",
                payload.commit_hash,
              ),
            );
          }
        } catch {
          /* ignore a broken event */
        }
      };
    } catch {
      es = null;
    }
    const poll = window.setInterval(() => {
      if (!tableSpinningRef.current) void loadTable();
    }, 4000);
    return () => {
      window.clearInterval(poll);
      es?.close();
    };
  }, [isRouletteTable, isAuthed, loadTable]);

  useEffect(() => {
    if (!isRouletteTable) {
      tableRoundRef.current = null;
      return;
    }
    const roundId = tableSnap?.round_id ?? null;
    if (!roundId) return;
    const prev = tableRoundRef.current;
    if (prev === roundId) return;
    tableRoundRef.current = roundId;
    if (placeLogRef.current.length && !prev) return;
    setOptimisticChips([]);
    const seated = lastTableBetsToDraft(
      (tableSnap?.my_bets || []).map((row) => ({ bet: row.bet, stake_rub: row.stake_rub })),
    );
    setPlaceLog(
      seated.map((chip) => ({
        bet: chip.bet,
        amount: chip.amount,
        localId: nextPlaceId.current++,
      })),
    );
  }, [isRouletteTable, tableSnap?.round_id]);

  /**
   * Zero reserves ×36 of the stake, so its table max is far below red/black.
   * After a bet switch, pull an over-limit stake down to the new max once.
   */
  useEffect(() => {
    if (!isRoulette || isRouletteTable || !clampOnBetSwitch.current) return;
    if (!quote || quote.bet !== rouletteBet) return;
    clampOnBetSwitch.current = false;
    if (stakeNumber > quote.max_bet_rub) setStake(String(quote.max_bet_rub));
  }, [isRoulette, isRouletteTable, quote, rouletteBet, stakeNumber]);

  function setMode(next: CasinoPlayMode) {
    const nextParams = new URLSearchParams(params);
    nextParams.set("mode", next);
    if (next !== "house") {
      nextParams.delete("view");
      nextParams.delete("ht");
    }
    setParams(nextParams, { replace: true });
  }

  function setHouseTableView(table: boolean) {
    const nextParams = new URLSearchParams(params);
    nextParams.set("mode", "house");
    if (table) {
      nextParams.set("view", "table");
    } else {
      nextParams.delete("view");
      nextParams.delete("ht");
    }
    setParams(nextParams, { replace: true });
  }

  useEffect(() => {
    refreshWallet();
  }, [refreshWallet]);

  const loadQuote = useCallback(() => {
    if (!isHousePlay || stakeNumber <= 0) return;
    getCasinoPlayQuote(
      stakeNumber,
      houseGameType,
      houseTableView ? houseBots : undefined,
      isRoulette ? rouletteBet : undefined,
    )
      .then(setQuote)
      .catch(() => undefined);
  }, [isHousePlay, houseGameType, stakeNumber, houseTableView, houseBots, isRoulette, rouletteBet]);

  useEffect(() => {
    if (pending) return;
    loadQuote();
  }, [loadQuote, pending]);

  const loadTape = useCallback(() => {
    if (!isHousePlay) return;
    getCasinoPlayTape(tapeTab, houseGameType)
      .then((payload) => setTape(payload.rows || []))
      .catch(() => undefined);
  }, [tapeTab, isHousePlay, houseGameType]);

  const requestTapeRefresh = useCallback(() => {
    if (fastPlayRef.current) {
      window.clearTimeout(tapeDelayRef.current);
      tapeDelayRef.current = window.setTimeout(() => {
        loadTape();
      }, 500);
      return;
    }
    loadTape();
  }, [loadTape]);

  useEffect(() => {
    loadTape();
  }, [loadTape]);

  const winField = quote && !quote.bound_error ? formatRub(quote.win_on_win_rub) : "—";

  function applyRoundWallet(amount: number, result: CasinoPlayResult) {
    const payout = Number(result.payout_rub) || 0;
    setWalletRub((prev) => {
      if (prev == null || !Number.isFinite(prev)) return prev;
      const next = prev - amount + payout;
      return Math.max(0, Math.round(next * 100) / 100);
    });
  }

  function holdWallet() {
    walletHoldRef.current = true;
    revealOnceRef.current = false;
    const snap = walletRubRef.current;
    setFrozenWallet(snap);
    window.dispatchEvent(new Event(CASINO_BALANCE_HOLD_EVENT));
  }

  function abortWalletHold() {
    walletHoldRef.current = false;
    revealOnceRef.current = true;
    pendingHouseRef.current = null;
    tableSpinningRef.current = false;
    wheelParkedRef.current = false;
    tableSettleOptionalRef.current = false;
    setFrozenWallet(null);
    window.dispatchEvent(new Event(CASINO_BALANCE_RELEASE_EVENT));
  }

  function notifyCardReveal() {
    const fn = cardRevealWaiterRef.current;
    if (!fn) return;
    cardRevealWaiterRef.current = null;
    fn();
  }

  function waitForCardReveal(result: CasinoPlayResult): Promise<void> {
    const live = result.phase === "player_turn" || result.outcome?.kind === "pending";
    const skip = prefersCasinoReducedMotion();
    const ms = houseCardsRevealMs({
      playerCount: cardsFromPlayResult(result, "player").length,
      houseCount: cardsFromPlayResult(result, "house").length,
      liveHouse: live,
      skipMotion: skip,
    });
    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        cardRevealWaiterRef.current = null;
        resolve();
      };
      cardRevealWaiterRef.current = finish;
      window.setTimeout(finish, skip ? 80 : ms + 250);
    });
  }

  function releaseCardWalletHold() {
    walletHoldRef.current = false;
    revealOnceRef.current = true;
    setFrozenWallet(null);
    window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
  }

  function startTableSpin(snap: CasinoRouletteTableSnapshot) {
    const pocket = snap.pocket;
    if (!snap.round_id || !isRoulettePocket(pocket)) return;
    if (tableSpunRound.current === snap.round_id) return;
    tableSpunRound.current = snap.round_id;
    tableStakeAtSpin.current = snap.my_stake_rub || tableSnapRef.current?.my_stake_rub || 0;
    const remembered = lastTableBetsToDraft(
      (snap.my_bets || tableSnapRef.current?.my_bets || []).map((row) => ({
        bet: row.bet,
        stake_rub: row.stake_rub,
      })),
    );
    if (remembered.length) {
      writeRouletteLastTableBets(remembered);
      setLastTableBets(remembered);
    }
    tableSettleOptionalRef.current = snap.status === "settled";
    wheelParkedRef.current = false;
    holdWallet();
    tableSpinningRef.current = true;
    const next = { ...snap, status: "spinning", pocket: Number(pocket) };
    tableSnapRef.current = next;
    setTableSnap(next);
    setSpinPlan(makeRouletteSpinPlan(prefersCasinoReducedMotion()));
    setSpinning(true);
    setLast(null);
    setSpins((prev) => rouletteHistoryWithoutRound(prev, snap.round_id));
  }
  startTableSpinRef.current = startTableSpin;

  function revealRouletteRound() {
    const house = pendingHouseRef.current;
    const table = pendingTableSettle.current;
    if (!rouletteTableRevealReady(tableSpinningRef.current, wheelParkedRef.current)) return;
    const frozen = frozenWallet;

    if (!revealOnceRef.current) {
      revealOnceRef.current = true;
      walletHoldRef.current = false;
      tableSpinningRef.current = false;
      setFrozenWallet(null);
      setSpinning(false);
      setPending(false);
      setSpinPlan(null);
      setTableSnap((prev) => {
        if (!prev || rouletteTableAcceptsBets(prev.status)) return prev;
        const next = { ...prev, status: "open" };
        tableSnapRef.current = next;
        return next;
      });
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      if (isRouletteTable && !table) void loadTable();
    }

    if (house) {
      pendingHouseRef.current = null;
      if (house.quote) setQuote(house.quote);
      if (!house.idempotent) {
        const amount = Number(house.stake_rub) || stakeRef.current;
        const payout = Number(house.payout_rub) || 0;
        const base = frozen ?? walletRubRef.current;
        if (base != null && Number.isFinite(base)) {
          setWalletRub(Math.max(0, Math.round((base - amount + payout) * 100) / 100));
        } else {
          applyRoundWallet(amount, house);
        }
      }
      const record = spinRecordOf(house);
      if (record) setSpins((prev) => mergeRouletteHistory(prev, [record]));
      requestTapeRefresh();
      const won = house.outcome?.kind === "win";
      const pocket = pocketOf(house);
      const where = pocket == null ? "" : ` · ${pocket}`;
      if (!fastPlayRef.current) {
        haptic(won ? "win" : "lose");
        if (won) toast.success(`Выигрыш ${formatRub(Number(house.payout_rub))}${where}`);
        else toast.error(`Проигрыш${where}`);
      }
    }
    if (table) {
      setLast({
        success: true,
        game_id: table.roundId,
        game_type: "roulette",
        outcome: { kind: table.won ? "win" : "loss", pocket: table.pocket, bet: table.bet },
        stake_rub: String(table.stake),
        commission_rub: "0",
        payout_rub: String(table.payout),
        pocket: table.pocket,
        bet: table.bet,
        won: table.won,
        rng: { commit: table.commit },
      });
      setSpins((prev) =>
        mergeRouletteHistory(prev, [
          {
            id: table.roundId || String(table.pocket),
            pocket: table.pocket,
            color: roulettePocketColor(table.pocket),
            bet: table.bet,
          },
        ]),
      );
      pendingTableSettle.current = null;
      haptic(table.won ? "win" : "lose");
      refreshWallet();
      void loadTable();
    }
  }

  holdWalletRef.current = holdWallet;
  revealRouletteRoundRef.current = revealRouletteRound;

  async function playOnce(amount: number, pace: "manual" | "auto"): Promise<CasinoPlayResult> {
    setRolling(true);
    const holdCards = isCardHouse;
    if (holdCards) holdWallet();
    try {
      const result = await playCasinoHouseRound(amount, houseGameType, isRoulette ? rouletteBet : undefined);
      setLast(result);
      if (result.quote) setQuote(result.quote);
      if (holdCards) {
        setRolling(false);
        await waitForCardReveal(result);
        if (!result.idempotent) applyRoundWallet(amount, result);
        if (pace === "manual" && result.phase !== "player_turn") loadTape();
        releaseCardWalletHold();
        return result;
      }
      if (!result.idempotent) applyRoundWallet(amount, result);
      if (pace === "manual" && result.phase !== "player_turn") loadTape();
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      const wait = rollDurationMs(pace);
      if (wait) await new Promise((resolve) => window.setTimeout(resolve, wait));
      return result;
    } catch (error) {
      if (holdCards) abortWalletHold();
      throw error;
    } finally {
      setRolling(false);
    }
  }

  async function playHouseTableRound() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/pvp_dice?mode=house&view=table");
      return;
    }
    if (quote?.bound_error) {
      toast.error(quote.bound_error);
      return;
    }
    setPending(true);
    setRolling(true);
    haptic("bet");
    try {
      const next = await createCasinoHouseTable({
        stake_rub: stakeNumber,
        max_seats: 1,
        house_bot_count: houseBots,
      });
      setHouseSnap(next);
      navigate(
        {
          pathname: casinoTo(`/casino/play/${gameId}`),
          search: `?mode=house&view=table&ht=${encodeURIComponent(next.table_id)}`,
        },
        { replace: true },
      );
      const mine = next.seats.find((row) => row.is_self);
      const payout = Number(mine?.payout_rub || 0);
      applyRoundWallet(stakeNumber, { payout_rub: payout } as CasinoPlayResult);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      loadTape();
      const wait = rollDurationMs("manual");
      if (wait) await new Promise((resolve) => window.setTimeout(resolve, wait));
      if (next.choice) {
        haptic("selection");
        toast.info("Ничья с ботом — заберите выигрыш или перебросьте один раз");
      } else if (next.last_round?.kind === "push") {
        haptic("selection");
        toast.info("Ставка вернулась");
      } else if (mine?.won) {
        haptic("win");
        toast.success(`Выигрыш ${formatRub(payout)}`);
      } else {
        haptic("lose");
        toast.error("Проигрыш");
      }
    } catch (error) {
      const tableId = apiErrorTableId(error);
      const message = error instanceof ApiError ? error.message : "Не удалось сыграть";
      if (tableId) {
        toast.error(message, {
          action: {
            label: "Встать",
            onClick: () => {
              void leaveCasinoHouseTable(tableId)
                .then(() => {
                  window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
                  toast.success("Вы встали со стола");
                })
                .catch((leaveErr) => {
                  toast.error(leaveErr instanceof ApiError ? leaveErr.message : "Не удалось встать");
                });
            },
          },
        });
      } else {
        toast.error(message);
      }
    } finally {
      setPending(false);
      window.setTimeout(() => setRolling(false), 50);
    }
  }

  async function resolveHouseChoice(action: "take" | "reroll") {
    if (!houseSnap?.table_id || !houseSnap.choice) return;
    setPending(true);
    if (action === "reroll") setRolling(true);
    haptic("selection");
    try {
      const next = await resolveCasinoHouseTable(houseSnap.table_id, action);
      setHouseSnap(next);
      const mine = next.seats.find((row) => row.is_self);
      const payout = Number(mine?.payout_rub || 0);
      applyRoundWallet(0, { payout_rub: payout } as CasinoPlayResult);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      refreshWallet();
      loadTape();
      if (action === "reroll") {
        const wait = rollDurationMs("manual");
        if (wait) await new Promise((resolve) => window.setTimeout(resolve, wait));
      }
      if (next.last_round?.kind === "push") {
        haptic("selection");
        toast.info("Ставка вернулась");
      } else if (mine?.won) {
        haptic("win");
        toast.success(`Выигрыш ${formatRub(payout)}`);
      } else {
        haptic("lose");
        toast.error("Проигрыш");
      }
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось закрыть раунд");
    } finally {
      setPending(false);
      setRolling(false);
    }
  }

  /**
   * One roulette spin. The pocket is already decided by the server when the wheel
   * starts decelerating; the result stays hidden until the wheel parks on it.
   */
  async function onSpin() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/roulette?mode=house");
      return;
    }
    if (pending || spinning) return;
    if (stakeNumber <= 0) {
      toast.error("Ставка должна быть больше нуля");
      return;
    }
    if (walletRub != null && stakeNumber > walletRub) {
      toast.error("Недостаточно средств на балансе");
      return;
    }
    if (quote?.bound_error) {
      toast.error(quote.bound_error);
      return;
    }
    const plan = makeRouletteSpinPlan(prefersCasinoReducedMotion() || fastPlay);
    holdWallet();
    setSpinPlan(plan);
    setPending(true);
    setSpinning(true);
    setLast(null);
    pendingHouseRef.current = null;
    if (!fastPlay) haptic("bet");
    try {
      const result = await playCasinoHouseRound(stakeNumber, "roulette", rouletteBet);
      pendingHouseRef.current = result;
      setLast(result);
      if (pocketOf(result) == null) revealRouletteRoundRef.current();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось сыграть");
      setSpinning(false);
      setPending(false);
      setSpinPlan(null);
      abortWalletHold();
    }
  }

  function enqueueTableOp(op: () => Promise<void>) {
    const run = tableQueueRef.current.then(op, op);
    tableQueueRef.current = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }

  function bumpWallet(delta: number) {
    setWalletRub((prev) => {
      if (prev == null || !Number.isFinite(prev)) return prev;
      return Math.max(0, Math.round((prev + delta) * 100) / 100);
    });
  }

  function onTablePlace(betKey: RouletteBetKey) {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/roulette?mode=players");
      return;
    }
    if (spinning || tableBusy) return;
    if (tableSnap && !rouletteTableAcceptsBets(tableSnap.status)) {
      toast.error("Раунд уже крутится");
      return;
    }
    if (stakeNumber <= 0) {
      toast.error("Выберите фишку");
      return;
    }
    const { even, straight } = tableSpotCaps(tableSnap);
    const cap = rouletteTableSpotMax(betKey, even, straight);
    const already = rouletteDraftTotal(placeLog.filter((chip) => chip.bet === betKey));
    if (stakeNumber + already > cap) {
      toast.error(
        cap + 0.005 < even
          ? `На число максимум ${formatRub(cap)} — дом держит выплату ×36. Фишка ${formatRub(stakeNumber)} не проходит.`
          : `На это поле максимум ${formatRub(cap)}.`,
      );
      return;
    }
    if (walletRub != null && stakeNumber > walletRub) {
      toast.error("Недостаточно средств на балансе");
      return;
    }
    if (placeLog.length >= ROULETTE_TABLE_DRAFT_MAX) {
      toast.error("Слишком много фишек");
      return;
    }
    const chip: TableLiveChip = { bet: betKey, amount: stakeNumber, localId: nextPlaceId.current++ };
    haptic("bet");
    setPlaceLog((prev) => [...prev, chip]);
    setOptimisticChips((prev) => [...prev, chip]);
    bumpWallet(-stakeNumber);
    setPlacingCount((count) => count + 1);
    void enqueueTableOp(async () => {
      try {
        const snap = await postCasinoRouletteTableBet(chip.amount, String(chip.bet));
        applyTableSnap(snap);
        setOptimisticChips((prev) => dropLiveChip(prev, chip.localId));
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        refreshWallet();
      } catch (error) {
        setPlaceLog((prev) => dropLiveChip(prev, chip.localId));
        setOptimisticChips((prev) => dropLiveChip(prev, chip.localId));
        bumpWallet(chip.amount);
        toast.error(error instanceof ApiError ? error.message : "Не удалось поставить");
      } finally {
        setPlacingCount((count) => Math.max(0, count - 1));
      }
    });
  }

  function serverBetChips(): TableLiveChip[] {
    return lastTableBetsToDraft(
      (tableSnapRef.current?.my_bets || []).map((row) => ({ bet: row.bet, stake_rub: row.stake_rub })),
    ).map((chip) => ({ bet: chip.bet, amount: chip.amount, localId: nextPlaceId.current++ }));
  }

  function onTableUndo() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/roulette?mode=players");
      return;
    }
    if (tableBusy || spinning) return;
    if (tableSnap && !rouletteTableAcceptsBets(tableSnap.status)) {
      toast.error("Раунд уже крутится");
      return;
    }
    if (!placeLogRef.current.length) {
      const seated = serverBetChips();
      if (!seated.length) {
        toast.error("На столе нет ваших фишек");
        return;
      }
      placeLogRef.current = seated;
      setPlaceLog(seated);
    }
    haptic("selection");
    setTableBusy(true);
    void enqueueTableOp(async () => {
      const step = rouletteUndoLastPlace(liveChipLog(placeLogRef.current));
      if (!step) {
        setTableBusy(false);
        return;
      }
      try {
        let snap = await postCasinoRouletteTableClear(String(step.bet));
        if (step.remainder > 0) {
          snap = await postCasinoRouletteTableBet(step.remainder, String(step.bet));
        }
        applyTableSnap(snap);
        setPlaceLog((prev) => prev.slice(0, -1));
        setOptimisticChips((prev) => prev.filter((chip) => chip.bet !== step.bet));
        bumpWallet(step.removed);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        refreshWallet();
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : "Не удалось снять фишку");
      } finally {
        setTableBusy(false);
      }
    });
  }

  function onTableRepeat() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/roulette?mode=players");
      return;
    }
    if (tableBusy || spinning) return;
    if (tableSnap && !rouletteTableAcceptsBets(tableSnap.status)) {
      toast.error("Раунд уже крутится");
      return;
    }
    if (!lastTableBets.length) {
      toast.error("Нет прошлого расклада");
      return;
    }
    const adding = mergeRouletteDraftBySpot(lastTableBets);
    const base = placeLogRef.current.length ? placeLogRef.current : serverBetChips();
    const { even, straight } = tableSpotCaps(tableSnap);
    for (const chip of adding) {
      const already = rouletteDraftTotal(base.filter((row) => row.bet === chip.bet));
      const cap = rouletteTableSpotMax(chip.bet, even, straight);
      if (chip.amount + already > cap + 0.001) {
        toast.error(`На «${rouletteBetSpec(chip.bet).title}» максимум ${formatRub(cap)}.`);
        return;
      }
    }
    const payload = rouletteDraftConfirmPayload(adding);
    const total = rouletteDraftTotal(adding);
    if (!payload.length) return;
    if (walletRub != null && total > walletRub) {
      toast.error("Недостаточно средств на балансе");
      return;
    }
    if (payload.length > ROULETTE_TABLE_DRAFT_MAX) {
      toast.error("Слишком много фишек");
      return;
    }
    haptic("bet");
    const chips: TableLiveChip[] = adding.map((chip) => ({
      bet: chip.bet,
      amount: chip.amount,
      localId: nextPlaceId.current++,
    }));
    if (!placeLogRef.current.length && base.length) {
      placeLogRef.current = base;
    }
    setPlaceLog((prev) => [...(prev.length ? prev : base), ...chips]);
    setOptimisticChips(chips);
    bumpWallet(-total);
    setTableBusy(true);
    void enqueueTableOp(async () => {
      try {
        const snap = await postCasinoRouletteTableBets(payload);
        applyTableSnap(snap);
        setOptimisticChips([]);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        refreshWallet();
      } catch (error) {
        setPlaceLog((prev) => prev.filter((chip) => !chips.some((added) => added.localId === chip.localId)));
        setOptimisticChips([]);
        bumpWallet(total);
        toast.error(error instanceof ApiError ? error.message : "Не удалось повторить ставки");
      } finally {
        setTableBusy(false);
      }
    });
  }

  function onTableClearSpot(betKey: RouletteBetKey) {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/roulette?mode=players");
      return;
    }
    if (tableBusy || spinning) return;
    const mine = (placeLogRef.current.length ? placeLogRef.current : serverBetChips()).filter(
      (chip) => chip.bet === betKey,
    );
    if (!mine.length) {
      toast.error("На этой клетке нет ваших фишек");
      return;
    }
    if (tableSnap && !rouletteTableAcceptsBets(tableSnap.status)) {
      toast.error("Раунд уже крутится");
      return;
    }
    const removed = rouletteDraftTotal(mine);
    haptic("selection");
    setTableBusy(true);
    void enqueueTableOp(async () => {
      try {
        const snap = await postCasinoRouletteTableClear(String(betKey));
        applyTableSnap(snap);
        setPlaceLog((prev) => prev.filter((chip) => chip.bet !== betKey));
        setOptimisticChips((prev) => prev.filter((chip) => chip.bet !== betKey));
        bumpWallet(removed);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        refreshWallet();
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : "Не удалось снять фишку");
      } finally {
        setTableBusy(false);
      }
    });
  }

  async function onTableClearAll() {
    if (tableBusy || spinning) return;
    if (!isAuthed) return;
    if (!placeLog.length && (tableSnap?.my_stake_rub || 0) <= 0) {
      toast.error("На столе нет ваших фишек");
      return;
    }
    if (tableSnap && !rouletteTableAcceptsBets(tableSnap.status)) {
      toast.error("Раунд уже крутится");
      return;
    }
    const restored = rouletteDraftTotal(placeLog) || tableSnap?.my_stake_rub || 0;
    setTableBusy(true);
    void enqueueTableOp(async () => {
      try {
        const snap = await postCasinoRouletteTableClear();
        applyTableSnap(snap);
        setPlaceLog([]);
        setOptimisticChips([]);
        bumpWallet(restored);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        refreshWallet();
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : "Не удалось снять фишки");
      } finally {
        setTableBusy(false);
      }
    });
  }

  async function onBet() {
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/play/${gameId || "pvp_dice"}?mode=${mode}`);
      return;
    }
    if (isRouletteTable) return;
    if (isRouletteHouse) {
      await onSpin();
      return;
    }
    if (houseTableView) {
      await playHouseTableRound();
      return;
    }
    if (!isHousePlay) return;
    if (isBlackjackHouse && last?.phase === "player_turn") return;
    if (quote?.bound_error) {
      toast.error(quote.bound_error);
      return;
    }
    setPending(true);
    haptic("bet");
    try {
      const result = await playOnce(stakeNumber, "manual");
      const kind = result.outcome?.kind;
      if (result.phase === "player_turn" || kind === "pending") {
        haptic("selection");
        return;
      }
      const won = kind === "win";
      const tie = kind === "tie";
      haptic(won ? "win" : "lose");
      if (won) toast.success(`Выигрыш ${formatRub(Number(result.payout_rub))}`);
      else if (tie) toast.info("Ничья · ставка вернулась");
      else toast.error("Проигрыш");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось сыграть");
    } finally {
      setPending(false);
    }
  }

  async function onBlackjackAction(action: "hit" | "stand") {
    if (!last?.game_id || last.phase !== "player_turn") return;
    setActing(true);
    haptic("selection");
    try {
      const result = await playCasinoBlackjackAction(last.game_id, action);
      const finished = result.phase !== "player_turn" && result.outcome?.kind !== "pending";
      if (finished) holdWallet();
      setLast(result);
      await waitForCardReveal(result);
      if (result.phase === "player_turn" || result.outcome?.kind === "pending") return;
      applyRoundWallet(0, result);
      loadTape();
      releaseCardWalletHold();
      const kind = result.outcome?.kind;
      const won = kind === "win";
      const tie = kind === "tie";
      haptic(won ? "win" : "lose");
      if (won) toast.success(`Выигрыш ${formatRub(Number(result.payout_rub))}`);
      else if (tie) toast.info("Ничья · ставка вернулась");
      else toast.error("Проигрыш");
    } catch (error) {
      abortWalletHold();
      toast.error(error instanceof ApiError ? error.message : "Не удалось сделать ход");
    } finally {
      setActing(false);
    }
  }

  async function onAuto() {
    if (!isHousePlay || !isAuthed) {
      await onBet();
      return;
    }
    const count = Math.max(1, Math.min(50, Number.parseInt(autoCount, 10) || 1));
    const base = stakeNumber;
    const profitStop = Number(stopProfit) || 0;
    const lossStop = Number(stopLoss) || 0;
    let current = base;
    let pnl = 0;
    autoStop.current = false;
    setPending(true);
    setHapticMuted(true);
    try {
      for (let i = 0; i < count; i += 1) {
        if (autoStop.current) break;
        const result = await playOnce(current, "auto");
        const payout = Number(result.payout_rub) || 0;
        const won = result.outcome?.kind === "win";
        pnl += payout - current;
        if (profitStop > 0 && pnl >= profitStop) break;
        if (lossStop > 0 && pnl <= -lossStop) break;
        if (won) {
          current = onWin === "reset" ? base : Math.round(current * (1 + (Number(onWinPct) || 0) / 100) * 100) / 100;
        } else {
          current = onLose === "reset" ? base : Math.round(current * (1 + (Number(onLosePct) || 0) / 100) * 100) / 100;
        }
        if (quote) {
          current = Math.min(quote.max_bet_rub, Math.max(quote.min_bet_rub, current));
        }
        setStake(String(current));
      }
    } catch (error) {
      const rateLimited = error instanceof ApiError && error.status === 429;
      toast.error(
        rateLimited
          ? "Слишком часто — авто остановлена. Подожди несколько секунд и запусти снова."
          : error instanceof ApiError
            ? error.message
            : "Автоигра остановлена",
      );
    } finally {
      setHapticMuted(false);
      setPending(false);
      loadTape();
    }
  }

  async function openFair() {
    setFairOpen(true);
    if (!isAuthed) return;
    try {
      const next = await getCasinoFairnessSession();
      setSession(next);
      setClientSeed(next.client_seed);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось открыть сессию честности");
    }
  }

  const displayWallet = visibleCasinoWallet(
    walletRub,
    frozenWallet,
    spinning || (isCardHouse && frozenWallet != null),
  );
  const minBet = isRouletteTable ? tableSnap?.min_bet_rub ?? 10 : quote?.min_bet_rub ?? 10;
  const evenMax = isRouletteTable
    ? tableSnap?.max_even_bet_rub ?? tableSnap?.max_bet_rub ?? 100000
    : quote?.max_bet_rub ?? 100000;
  const straightMax = isRouletteTable
    ? tableSnap?.max_straight_bet_rub ?? evenMax
    : quote?.max_bet_rub ?? 100000;
  const maxBet = isRouletteTable ? evenMax : quote?.max_bet_rub ?? 100000;
  const lastWon = last?.outcome?.kind === "win";
  const betSpec = rouletteBetSpec(rouletteBet);
  const lowBalance = isRoulette && displayWallet != null && stakeNumber > displayWallet;
  const invalidStake = isRoulette && stakeNumber <= 0;
  const confirmedStake = Math.max(tableSnap?.my_stake_rub || 0, rouletteDraftTotal(placeLog));
  const canRepeatTable =
    isRouletteTable &&
    isAuthed &&
    placingCount === 0 &&
    !tableBusy &&
    (tableSnap == null || rouletteTableAcceptsBets(tableSnap.status));
  const mineSeat = (tableSnap?.my_bets || tableSnap?.players || []).find(
    (row) => mineId != null && row.user_id === mineId,
  );
  const draftActor =
    mineId == null
      ? null
      : {
          user_id: mineId,
          display_name: mineSeat?.display_name || user?.display_name || user?.username || "Вы",
          initial: mineSeat?.initial || String(user?.display_name || user?.username || "Я").slice(0, 1).toUpperCase(),
          avatar_url:
            mineSeat?.avatar_url ?? (typeof user?.avatar_url === "string" ? user.avatar_url : null),
        };
  const rouletteResult: CasinoRouletteResult | null = (() => {
    if (isRouletteTable && tableSnap?.pocket != null) {
      const pocket = tableSnap.pocket;
      const fromLast = last && pocketOf(last) === pocket ? last : null;
      return {
        pocket,
        bet: fromLast && isRouletteBetKey(fromLast.bet) ? fromLast.bet : rouletteBet,
        won: fromLast ? fromLast.outcome?.kind === "win" || Boolean(fromLast.won) : false,
        stakeRub: fromLast ? Number(fromLast.stake_rub) || 0 : 0,
        payoutRub: fromLast ? Number(fromLast.payout_rub) || 0 : 0,
        commit: tableSnap.commit_hash,
      };
    }
    if (!isRoulette || !last) return null;
    const pocket = pocketOf(last);
    if (pocket == null) return null;
    return {
      pocket,
      bet: isRouletteBetKey(last.bet) ? last.bet : rouletteBet,
      won: last.outcome?.kind === "win",
      stakeRub: Number(last.stake_rub) || 0,
      payoutRub: Number(last.payout_rub) || 0,
      commit: last.rng?.commit,
    };
  })();
  const roulettePhase = rouletteUiPhase({
    spinning: spinning || (pending && isRouletteHouse),
    stake: stakeNumber,
    wallet: displayWallet,
    boundError: isRouletteTable ? null : quote?.bound_error,
    result: rouletteResult && !spinning ? { won: rouletteResult.won } : null,
    authed: isAuthed,
  });

  return (
    <div className="casino-play" data-casino-play={gameId || ""}>
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        {game ? (
          <>
            <span className="casino-crumb-sep" aria-hidden>
              /
            </span>
            <span>{game.name}</span>
          </>
        ) : null}
      </nav>
      {gameId === "jackpot" || gameId === "raffle" || gameId === "fixed_room" || gameId === "nardy" || gameId === "russian_draughts" || isRoulette || isHeadToHead(gameId) ? null : (
      <div className="casino-play-modes">
        <CasinoModeSwitch mode={mode} onChange={setMode} playersDisabled={gameId === "roulette"} />
        {isCub ? (
          <div className="casino-mode-switch is-compact" role="tablist" aria-label="Стол против FocusBet" data-casino-house-view={houseTableView ? "table" : "solo"}>
            <button
              type="button"
              role="tab"
              aria-selected={!houseTableView}
              className={houseTableView ? "" : "is-on"}
              onClick={() => setHouseTableView(false)}
            >
              1×1
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={houseTableView}
              className={houseTableView ? "is-on" : ""}
              onClick={() => setHouseTableView(true)}
            >
              Стол 2–6
            </button>
          </div>
        ) : null}
      </div>
      )}
      {shell ? (
        <div className="casino-play-layout is-players" data-casino-play-shell={gameId}>
          {gameId === "holdem" && mode === "players" ? <CasinoPoker embedded /> : null}
          {gameId === "nardy" ? <CasinoNardy embedded /> : null}
          {gameId === "russian_draughts" ? <CasinoDraughts embedded /> : null}
          {gameId === "holdem" && mode === "house" ? (
            <PlayNote title={gameTitle}>
              Холдем на сайте — кэш-столы 2–6 с игроками, не раздача против FocusBet. Домашней NLHE нет. Откройте вкладку «С
              игроками».
            </PlayNote>
          ) : null}
          {gameId === "jackpot" ? <CasinoJackpot embedded /> : null}
          {gameId === "raffle" ? <CasinoRaffle embedded /> : null}
          {gameId === "fixed_room" && mode === "players" ? <CasinoFixedRooms embedded /> : null}
          {gameId === "fixed_room" && mode === "house" ? (
            <PlayNote title={gameTitle}>
              Фикс-комната — игроки друг против друга с одной ставкой. Колесо выбирает одного, FocusBet берёт рейк с банка.
            </PlayNote>
          ) : null}
          {gameId === "clan_war" && mode === "players" ? <CasinoClanWars embedded /> : null}
          {gameId === "clan_war" && mode === "house" ? (
            <PlayNote title={gameTitle}>
              Война кланов — две команды. Деньги списываются с кошельков бойцов, у клана банка нет. Не игра против дома.
            </PlayNote>
          ) : null}
        </div>
      ) : null}
      {shell ? null : isCardHouse ? (
        <p className="casino-muted">
          1×1 против FocusBet: HMAC-колода, каждый vs дом, выплата после комиссии. Стол 2–6 против дома ещё не подключен.
        </p>
      ) : null}
      {shell ? null : (
      <div className={`casino-play-layout${showPlayers ? " is-players" : ""}`}>
        {showPlayers ? null : (
        <aside className="casino-stake-panel" data-casino-stake="">
          <p className="casino-stake-kicker">Ставка</p>
          {isRoulette ? null : (
          <div className="casino-stake-tabs" role="tablist">
            <button type="button" className={tab === "manual" ? "is-on" : ""} onClick={() => setTab("manual")}>
              Вручную
            </button>
            {isBlackjackHouse || houseTableView ? null : (
            <button type="button" className={tab === "auto" ? "is-on" : ""} onClick={() => setTab("auto")} disabled={!isHousePlay}>
              Авто
            </button>
            )}
          </div>
          )}

          <label className="casino-field">
            <span>{isRouletteTable ? "Фишка" : "Сумма ставки"}</span>
            <div className={`casino-stake-row${isRoulette ? " is-stepper" : ""}`}>
              {isRoulette ? (
                <button
                  type="button"
                  className="casino-btn casino-btn-ghost"
                  aria-label={`Уменьшить ставку на ${ROULETTE_STAKE_STEP} рублей`}
                  disabled={spinning || pending || stakeNumber <= minBet}
                  onClick={() => {
                    haptic("selection");
                    setStake(String(clampStake(String(stakeNumber - ROULETTE_STAKE_STEP), minBet, walletCap(maxBet, displayWallet))));
                  }}
                >
                  −
                </button>
              ) : null}
              <input
                type="text"
                inputMode="decimal"
                value={stake}
                onChange={(event) => setStake(event.target.value)}
                aria-label="Сумма ставки"
                disabled={last?.phase === "player_turn" || spinning}
              />
              {isRoulette ? (
                <button
                  type="button"
                  className="casino-btn casino-btn-ghost"
                  aria-label={`Увеличить ставку на ${ROULETTE_STAKE_STEP} рублей`}
                  disabled={spinning || pending || stakeNumber >= walletCap(maxBet, displayWallet)}
                  onClick={() => {
                    haptic("selection");
                    setStake(String(clampStake(String(stakeNumber + ROULETTE_STAKE_STEP), minBet, walletCap(maxBet, displayWallet))));
                  }}
                >
                  +
                </button>
              ) : null}
              <button
                type="button"
                className="casino-btn casino-btn-ghost"
                disabled={spinning || (isRoulette && pending)}
                onClick={() => { haptic("selection"); setStake(String(clampStake(String(stakeNumber / 2), minBet, maxBet))); }}
              >
                ½
              </button>
              <button
                type="button"
                className="casino-btn casino-btn-ghost"
                data-casino-x2=""
                disabled={spinning || (isRoulette && pending)}
                onClick={() => {
                  haptic("selection");
                  setStake(String(doubleOrAllIn(stakeNumber, minBet, maxBet, displayWallet)));
                }}
              >
                ×2
              </button>
            </div>
            <span className="casino-muted">{formatRub(stakeNumber)}</span>
          </label>

          {isRoulette ? (
            <span
              className="casino-muted"
              data-casino-wallet=""
              data-casino-wallet-frozen={
                (spinning || isCardHouse) && frozenWallet != null ? "1" : "0"
              }
              data-casino-roulette-straight-max={isRouletteTable ? String(straightMax) : undefined}
            >
              {isRouletteTable
                ? `Баланс ${displayWallet == null ? "—" : formatRub(displayWallet)} · цвет ${formatRub(minBet)}—${formatRub(evenMax)} · число до ${formatRub(straightMax)}`
                : `Баланс ${displayWallet == null ? "—" : formatRub(displayWallet)} · лимит ${formatRub(minBet)}—${formatRub(maxBet)}`}
            </span>
          ) : null}

          <label className="casino-field">
            <span>{isRouletteTable ? "На столе" : "Выигрыш при победе"}</span>
            <input
              type="text"
              readOnly
              value={
                isRouletteTable
                  ? formatRub(confirmedStake)
                  : isHousePlay
                    ? winField
                    : "—"
              }
              className="is-readonly"
            />
          </label>

          {isCub ? (
            <div className="casino-field">
              <span>Контроль игры</span>
              <p className="casino-game-control">
                {houseTableView
                  ? `Стол против FocusBet: ${houseBots} ботов дома. Выигрыш — если ваша грань строго больше каждой грани дома: ${quote ? `×${quote.payout_multiplier}` : `×${houseBots + 1}`}. Ничья с ботом — забрать или один переброс. Проигрыш любому — вся ставка. 1×1 без этого выбора.`
                  : `Сейчас быстрый 1×1 против FocusBet. Коэффициент ${quote ? `×${quote.payout_multiplier}` : "×2"}${quote?.win_probability != null ? `, шанс ${(quote.win_probability * 100).toFixed(0)}%` : ""}. Стол 2–6 — вкладка «Стол 2–6»: вы vs N ботов дома, коэффициент растёт с числом ботов.`}
              </p>
            </div>
          ) : isCardHouse ? (
            <div className="casino-field">
              <span>Контроль игры</span>
              <p className="casino-game-control">
                1×1 против FocusBet. {isBlackjackHouse
                  ? "Добрать или оставить. У дилера одна карта скрыта, потом он сам до 17. "
                  : "Карты с HMAC-колоды, не клиентский победитель. "}
                Коэффициент{" "}
                {quote ? `×${quote.payout_multiplier}` : "×2"}: при 100 ₽ выплата {winField}. Ничья возвращает ставку. Стол 2–6 vs
                дом — следующим срезом.
              </p>
            </div>
          ) : isRoulette ? null : gameId === "raffle" ? null : (
            <p className="casino-muted">Выберите «С игроками», чтобы открыть лобби этой игры.</p>
          )}

          {houseTableView ? (
            <div className="casino-field">
              <span>Ботов дома</span>
              <div className="casino-stake-chips" data-casino-house-bots="" data-casino-house-odds={quote ? String(quote.payout_multiplier) : String(houseBots + 1)}>
                {[2, 3, 4, 5, 6].map((count) => (
                  <button
                    key={count}
                    type="button"
                    className={houseBots === count ? "is-on" : ""}
                    disabled={pending || Boolean(houseSnap?.choice)}
                    onClick={() => {
                      haptic("selection");
                      setHouseBots(count);
                    }}
                  >
                    {count}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {tab === "auto" && isHousePlay && !isBlackjackHouse && !houseTableView && !isRoulette ? (
            <div className="casino-auto">
              <label>
                Число ставок
                <input value={autoCount} onChange={(event) => setAutoCount(event.target.value)} inputMode="numeric" />
              </label>
              <label>
                При выигрыше
                <select value={onWin} onChange={(event) => setOnWin(event.target.value as "reset" | "increase")}>
                  <option value="reset">сброс к базе</option>
                  <option value="increase">увеличить на %</option>
                </select>
              </label>
              {onWin === "increase" ? (
                <label>
                  % при выигрыше
                  <input value={onWinPct} onChange={(event) => setOnWinPct(event.target.value)} />
                </label>
              ) : null}
              <label>
                При проигрыше
                <select value={onLose} onChange={(event) => setOnLose(event.target.value as "reset" | "increase")}>
                  <option value="reset">сброс к базе</option>
                  <option value="increase">увеличить на %</option>
                </select>
              </label>
              {onLose === "increase" ? (
                <label>
                  % при проигрыше
                  <input value={onLosePct} onChange={(event) => setOnLosePct(event.target.value)} />
                </label>
              ) : null}
              <label>
                Стоп по прибыли, ₽
                <input value={stopProfit} onChange={(event) => setStopProfit(event.target.value)} />
              </label>
              <label>
                Стоп по убытку, ₽
                <input value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} />
              </label>
            </div>
          ) : null}

          {quote?.bound_error && !isRouletteTable ? <p className="casino-duel-error">{quote.bound_error}</p> : null}
          {isRoulette && lowBalance ? (
            <p className="casino-duel-error">Недостаточно средств: на балансе {formatRub(walletRub ?? 0)}.</p>
          ) : null}
          {isRoulette && invalidStake ? <p className="casino-duel-error">Ставка должна быть больше нуля.</p> : null}

          {isRouletteHouse ? (
            <>
              <label className="casino-field casino-notify-toggle">
                <input
                  type="checkbox"
                  checked={fastPlay}
                  onChange={(event) => {
                    const on = event.target.checked;
                    setFastPlay(on);
                    writeRouletteFastPlay(on);
                  }}
                  data-casino-roulette-fast-toggle=""
                />
                Быстрая игра
              </label>
              <p className="casino-muted">Без анимации колеса — крутить можно сразу после ответа сервера.</p>
            </>
          ) : null}

          {isHousePlay ? (
            <>
              {isRouletteTable ? (
                <p className="casino-muted" data-casino-roulette-chip-hint="">
                  Фишка {formatRub(stakeNumber)} — клик сразу на стол. На число до {formatRub(straightMax)}, цвет до {formatRub(evenMax)}.
                </p>
              ) : (
              <button
                type="button"
                className="casino-btn casino-bet-btn"
                data-casino-house-play={houseGameType}
                aria-label={isRoulette ? "Крутить рулетку" : undefined}
                disabled={
                  pending ||
                  acting ||
                  spinning ||
                  last?.phase === "player_turn" ||
                  Boolean(houseSnap?.choice) ||
                  Boolean(quote && !quote.enabled) ||
                  (isAuthed && (lowBalance || invalidStake))
                }
                onClick={() => (tab === "auto" ? onAuto() : onBet())}
              >
                {pending
                  ? isRoulette
                    ? fastPlay
                      ? "Крутим…"
                      : "Колесо крутится…"
                    : "Идёт раунд…"
                  : spinning
                    ? fastPlay
                      ? "Крутим…"
                      : "Колесо крутится…"
                    : houseSnap?.choice
                    ? "Заберите или перебросьте"
                    : last?.phase === "player_turn"
                    ? "Ваш ход"
                    : !isAuthed
                      ? isRoulette
                        ? "Войти и крутить"
                        : "Войти и поставить"
                      : isRoulette
                        ? "Крутить"
                        : "Ставка"}
              </button>
              )}
              {pending && tab === "auto" ? (
                <button type="button" className="casino-btn casino-btn-ghost" onClick={() => { autoStop.current = true; }}>
                  Стоп
                </button>
              ) : null}
            </>
          ) : null}
          {houseTableView && houseSnap?.is_seated && houseSnap.status === "open" && !houseSnap.solo ? (
            <button
              type="button"
              className="casino-btn casino-btn-ghost"
              disabled={pending}
              onClick={() => {
                void leaveCasinoHouseTable(houseSnap.table_id)
                  .then((next) => {
                    setHouseSnap(next);
                    window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
                    toast.success("Вы встали со стола");
                    navigate(
                      { pathname: casinoTo(`/casino/play/${gameId}`), search: "?mode=house&view=table" },
                      { replace: true },
                    );
                  })
                  .catch((error) => {
                    toast.error(error instanceof ApiError ? error.message : "Не удалось встать");
                  });
              }}
            >
              Встать со стола
            </button>
          ) : null}
          <button type="button" className="casino-fair-link" onClick={() => void openFair()}>
            <ShieldCheck size={16} /> Честность
          </button>
        </aside>
        )}

        <section className="casino-play-canvas" data-casino-canvas="">
          {isRoulette ? null : (
            <>
          <p className="casino-play-kicker">Стол</p>
          <h1>{game?.name ?? gameId}</h1>
            </>
          )}
          {showHouseTable ? (
            <CasinoHouseTables
              snap={houseSnap}
              rolling={rolling}
              botCount={houseBots}
              resolving={pending}
              onTake={() => void resolveHouseChoice("take")}
              onReroll={() => void resolveHouseChoice("reroll")}
            />
          ) : showPlayers ? (
            <CasinoPlayersLobby
              gameType={gameId}
              stakeRub={stakeNumber > 0 ? stakeNumber : 50}
              onStakeChange={setStake}
            />
          ) : isRoulette ? (
            <CasinoRoulette
              bet={rouletteBet}
              onBetChange={(next) => {
                haptic("selection");
                clampOnBetSwitch.current = true;
                setRouletteBet(next);
              }}
              betsLocked={
                spinning ||
                (isRouletteTable
                  ? tableBusy || !rouletteTableAcceptsBets(tableSnap?.status)
                  : pending)
              }
              spinning={spinning}
              phase={roulettePhase}
              plan={spinPlan}
              result={rouletteResult}
              history={spins}
              formatRub={formatRub}
              tableSeats={isRouletteTable ? tableSnap?.players ?? [] : undefined}
              mineId={mineId}
              closesAt={isRouletteTable ? tableSnap?.closes_at ?? null : undefined}
              tableStatus={isRouletteTable ? tableSnap?.status : undefined}
              fastPlay={isRouletteHouse && fastPlay}
              onSettled={() => {
                wheelParkedRef.current = true;
                revealRouletteRoundRef.current();
              }}
              onPlaceSpot={isRouletteTable ? (next) => onTablePlace(next) : undefined}
              onClearSpot={isRouletteTable ? (next) => onTableClearSpot(next) : undefined}
              onClearAll={isRouletteTable ? () => void onTableClearAll() : undefined}
              draftChips={isRouletteTable ? optimisticChips : undefined}
              draftActor={isRouletteTable ? draftActor : undefined}
              onRepeat={isRouletteTable ? () => onTableRepeat() : undefined}
              onUndoLast={isRouletteTable ? () => onTableUndo() : undefined}
              canRepeat={canRepeatTable}
              ownStakeRub={isRouletteTable ? confirmedStake : 0}
              denominations={isRouletteTable ? ROULETTE_TABLE_CHIPS : ROULETTE_QUICK_STAKES}
              denomination={stakeNumber}
              onDenomination={(amount) => {
                haptic("selection");
                setStake(String(amount));
              }}
              denominationDisabled={spinning || pending}
              denominationMin={minBet}
              denominationMax={walletCap(maxBet, displayWallet)}
              fairness={isRouletteTable && tableSnap ? {
                roundId: tableSnap.round_id,
                commit: tableSnap.commit_hash,
                serverSeed: tableSnap.server_seed,
                clientSeed: tableSnap.client_seed,
                nonce: tableSnap.nonce,
              } : null}
            />
          ) : isCardHouse ? (
            <CasinoHouseCards
              gameType={gameId === "blackjack" ? "blackjack" : "baccara"}
              last={last}
              rolling={rolling}
              acting={acting}
              onHit={() => void onBlackjackAction("hit")}
              onStand={() => void onBlackjackAction("stand")}
              onRevealReady={notifyCardReveal}
            />
          ) : (
          <div className={`casino-cub-stage${last && isCub && !rolling ? (lastWon ? " is-win" : " is-lose") : ""}`}>
            {isCub ? (
              <>
                <CasinoDiceDuel
                  leftLabel="Вы"
                  rightLabel="FocusBet"
                  leftValue={pipsOf(last, "player")}
                  rightValue={pipsOf(last, "house")}
                  leftRolling={rolling}
                  rightRolling={rolling}
                />
                {last && !rolling ? (
                  <div className={`casino-round-result${lastWon ? " is-win" : " is-lose"}`}>
                    <strong>{lastWon ? "Победа" : "Поражение"}</strong>
                    <p>
                      Вы {pipsOf(last, "player") ?? "—"} · FocusBet {pipsOf(last, "house") ?? "—"} · ставка{" "}
                      {formatRub(Number(last.stake_rub))} · выплата {formatRub(Number(last.payout_rub))}
                    </p>
                    {last.rng?.commit ? <p className="casino-mono">commit {String(last.rng.commit).slice(0, 16)}…</p> : null}
                  </div>
                ) : (
                  <p className="casino-muted">
                    {rolling
                      ? "Бросок…"
                      : "Поставьте сумму слева. Слева ваш куб, справа — FocusBet. «Выигрыш при победе» — то, что придёт на баланс после комиссии."}
                  </p>
                )}
                <p className="casino-hmac-note">Исход считается HMAC против порога политики. Кубы показывают этот исход, не решают его.</p>
              </>
            ) : (
              <>
                <span className="casino-cub-face" aria-hidden>
                  {game?.emoji || "🎲"}
                </span>
                <p className="casino-muted">
                  {mode === "house"
                    ? "Несколько игроков против FocusBet: каждый со своей ставкой, боты могут играть за дом. Для этой игры стол ещё не подключен."
                    : "Откройте вкладку «С игроками»."}
                </p>
              </>
            )}
          </div>
          )}
        </section>

        {isHousePlay && !isRoulette ? (
        <section className="casino-tape" data-casino-tape="">
          <div className="casino-stake-tabs">
            {(["mine", "all", "high"] as const).map((id) => (
              <button key={id} type="button" className={tapeTab === id ? "is-on" : ""} onClick={() => setTapeTab(id)}>
                {id === "mine" ? "Мои" : id === "all" ? "Все" : "Крупные"}
              </button>
            ))}
          </div>
          {tape.length === 0 ? (
            <p className="casino-muted">Лента пуста.</p>
          ) : (
            <ul>
              {(isRoulette ? tape.slice(0, 8) : tape).map((row) => (
                <li key={row.game_id}>
                  <span>{row.player_label}</span>
                  <span>{formatRub(row.stake_rub)}</span>
                  <span className={row.won ? "is-win" : "is-lose"}>{row.won ? formatRub(row.payout_rub) : "−"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        ) : null}
      </div>
      )}

      {fairOpen ? (
        <div className="casino-modal" role="dialog" aria-label="Честность">
          <div className="casino-modal-card">
            <h2>Проверка честности</h2>
            <p>
              Хеш серверного сида публикуется до ставки. После ротации открывается прошлый сид. Карты считаются HMAC-SHA256 от
              client_seed:nonce:game_id:сторона. Кубик против FocusBet — HMAC-SHA256 от game_id:nonce; выигрыш, если число меньше порога политики.
              Рулетка — HMAC-SHA256 от client_seed:nonce:game_id:pocket по модулю 37, лунка 0–36.
            </p>
            {session ? (
              <>
                <label className="casino-field">
                  Хеш серверного сида
                  <input readOnly className="is-readonly casino-mono" value={session.commit_hash} />
                </label>
                <label className="casino-field">
                  Клиентский сид
                  <input value={clientSeed} onChange={(event) => setClientSeed(event.target.value)} className="casino-mono" />
                </label>
                <p className="casino-muted">nonce {session.nonce}</p>
                {session.previous_server_seed ? (
                  <p className="casino-mono">прошлый сид {session.previous_server_seed}</p>
                ) : null}
                <div className="casino-duels-actions">
                  <button
                    type="button"
                    className="casino-btn casino-btn-ghost"
                    onClick={() => {
                      setCasinoFairnessClientSeed(clientSeed.trim())
                        .then((next) => { setSession(next); toast.success("Сид записан"); })
                        .catch((error) => toast.error(error instanceof ApiError ? error.message : "Не сохранился"));
                    }}
                  >
                    Сохранить сид
                  </button>
                  <button
                    type="button"
                    className="casino-btn casino-btn-ghost"
                    disabled={!session.rotation_allowed}
                    onClick={() => {
                      rotateCasinoFairnessSession()
                        .then((next) => { setSession(next); setClientSeed(next.client_seed); toast.success("Сид сменён"); })
                        .catch((error) => toast.error(error instanceof ApiError ? error.message : "Ротация недоступна"));
                    }}
                  >
                    Ротация
                  </button>
                </div>
              </>
            ) : (
              <p className="casino-muted">{isAuthed ? "Сессия не загрузилась." : "Войдите, чтобы править клиентский сид."}</p>
            )}
            <p>
              <Link to={casinoTo("/casino/fairness")}>Открыть верификатор</Link>
            </p>
            <button type="button" className="casino-btn" onClick={() => setFairOpen(false)}>
              Закрыть
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
