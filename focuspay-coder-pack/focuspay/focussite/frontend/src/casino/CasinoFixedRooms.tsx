import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { ApiError, API_BASE, getToken } from "@/lib/api";
import {
  getCasinoRoom,
  getCasinoRooms,
  postCasinoRoom,
  postCasinoRoomBot,
  postCasinoRoomCancel,
  postCasinoRoomJoin,
  postCasinoRoomLeave,
  type CasinoRoomList,
  type CasinoRoomPlayer,
  type CasinoRoomSnapshot,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerAvatar, CasinoPlayerChip } from "./CasinoPlayerChip";
import { CasinoRoomLiveCanvas, mergeRoomSpinPayload, roomStatusLabel } from "./CasinoRoomLiveCanvas";
import { CasinoStartCountdown } from "./CasinoStartCountdown";
import { CASINO_BALANCE_EVENT, CASINO_BALANCE_HOLD_EVENT } from "./gameCatalog";
import { useWalletScopeRefresh } from "./walletScope";
import { WEIGHTED_REEL_SPIN_MS, WEIGHTED_REEL_WINNER_INDEX, buildWeightedReel } from "./weightedReel";
import { TelegramMainButton } from "./TelegramMainButton";

const STAKE_CHIPS = [10, 25, 50, 100, 250, 500];
const SEAT_CHOICES = [2, 3, 4, 5, 6];
const ROOMS_PLAY = "/casino/play/fixed_room?mode=players";
const SLOT_DESKTOP_PX = 72;
const SLOT_MOBILE_PX = 56;
const WINNER_INDEX = WEIGHTED_REEL_WINNER_INDEX;
const SPIN_MS = WEIGHTED_REEL_SPIN_MS;
const SHARE_LIGHTS = [86, 72, 58, 46, 38, 28, 20, 14];

function formatRub(value: number | string): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ₽`;
}

function errMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Не удалось выполнить запрос";
}

function previewPot(stake: number, seats: number, rakePercent: number): { pot: number; commission: number; net: number } {
  const pot = Math.round(stake * seats * 100) / 100;
  const commission = Math.round(pot * (rakePercent / 100) * 100) / 100;
  return { pot, commission, net: Math.round((pot - commission) * 100) / 100 };
}

function slotPx(): number {
  try {
    if (window.matchMedia("(max-width: 767px)").matches) return SLOT_MOBILE_PX;
  } catch {
    /* SSR */
  }
  return SLOT_DESKTOP_PX;
}

function shareColor(index: number): string {
  return `hsl(0 0% ${SHARE_LIGHTS[index % SHARE_LIGHTS.length]}%)`;
}

function shortHash(value: string, keep = 10): string {
  const text = value.trim();
  if (!text || text.length <= keep + 1) return text || "—";
  return `${text.slice(0, keep)}…`;
}

function reduceMotion(): boolean {
  try {
    if (document.documentElement.classList.contains("casino-reduce-motion")) return true;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function CasinoFixedRooms({ embedded = false }: { embedded?: boolean }) {
  const { roomId } = useParams();
  if (roomId) return <CasinoFixedRoomPage roomId={roomId} />;
  return <CasinoFixedRoomLobby embedded={embedded} />;
}

function CasinoFixedRoomLobby({ embedded }: { embedded: boolean }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [list, setList] = useState<CasinoRoomList | null>(null);
  const [error, setError] = useState("");
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({});
  const [createBusy, setCreateBusy] = useState(false);
  const [stake, setStake] = useState("250");
  const [maxSeats, setMaxSeats] = useState(4);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const stakeNumber = Number(stake.replace(",", ".")) || 0;
  const rake = list?.rake_percent ?? 5;
  const preview = previewPot(stakeNumber, maxSeats, rake);
  const rooms = useMemo(() => {
    const rows = list?.rooms ?? [];
    return [...rows]
      .filter((row) => (stakeNumber > 0 ? Number(row.stake_rub) === stakeNumber : true))
      .sort((a, b) =>
        sortDir === "asc" ? Number(a.stake_rub) - Number(b.stake_rub) : Number(b.stake_rub) - Number(a.stake_rub),
      )
      .sort((a, b) => Number(b.my_seat != null) - Number(a.my_seat != null));
  }, [list?.rooms, stakeNumber, sortDir]);

  async function load() {
    try {
      setList(await getCasinoRooms());
      setError("");
    } catch (err) {
      setError(errMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, [isAuthed]);

  useWalletScopeRefresh(() => void load());

  useEffect(() => {
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/rooms/events${qs}`, { withCredentials: true });
      es.onmessage = () => {
        void load();
      };
    } catch {
      /* poll only */
    }
    const poll = window.setInterval(() => void load(), 2500);
    return () => {
      es?.close();
      window.clearInterval(poll);
    };
  }, [isAuthed]);

  function needLogin() {
    goCasinoLogin(navigate, ROOMS_PLAY);
  }

  async function runRoom(roomId: string, fn: () => Promise<void>) {
    setBusyIds((current) => ({ ...current, [roomId]: true }));
    try {
      await fn();
    } finally {
      setBusyIds((current) => {
        const next = { ...current };
        delete next[roomId];
        return next;
      });
    }
  }

  async function onCreate() {
    if (!isAuthed) {
      needLogin();
      return;
    }
    if (!Number.isFinite(stakeNumber) || stakeNumber <= 0) {
      setError("Укажи ставку");
      return;
    }
    setCreateBusy(true);
    try {
      await postCasinoRoom(stakeNumber, maxSeats);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      await load();
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setCreateBusy(false);
    }
  }

  async function onJoin(row: CasinoRoomSnapshot) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    if (row.my_seat != null) {
      await load();
      return;
    }
    await runRoom(row.room_id, async () => {
      try {
        await postCasinoRoomJoin(row.room_id);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        await load();
      } catch (err) {
        toast.error(errMessage(err));
        void load();
      }
    });
  }

  async function onLeave(row: CasinoRoomSnapshot) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    await runRoom(row.room_id, async () => {
      try {
        if (row.can_cancel) await postCasinoRoomCancel(row.room_id);
        else await postCasinoRoomLeave(row.room_id);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        toast.success(row.can_cancel ? "Комната отменена" : "Вы вышли");
        await load();
      } catch (err) {
        toast.error(errMessage(err));
        void load();
      }
    });
  }

  async function onAddBot(row: CasinoRoomSnapshot) {
    if (!isAuthed) {
      needLogin();
      return;
    }
    await runRoom(row.room_id, async () => {
      try {
        await postCasinoRoomBot(row.room_id);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        await load();
      } catch (err) {
        toast.error(errMessage(err));
        void load();
      }
    });
  }

  const enabled = list?.enabled !== false;

  return (
    <div className="casino-rooms casino-table-lobby" data-casino-rooms="1">
      {embedded ? null : (
        <header className="casino-duels-head">
          <div>
            <nav className="casino-crumb" aria-label="Навигация">
              <Link to={casinoTo("/casino")}>Лобби</Link>
              <span className="casino-crumb-sep" aria-hidden>
                /
              </span>
              <span>Комнаты</span>
            </nav>
            <h1>Комнаты</h1>
          </div>
        </header>
      )}
      {!enabled ? <p className="casino-duel-error">Комнаты выключены в настройках.</p> : null}
      <section className="casino-create-card casino-create-card-table" data-casino-room-create="">
        <div className="casino-create-card-head">
          <div>
            <p className="casino-create-eyebrow">Рулетка · общий банк</p>
            <h2>Новая комната</h2>
            <p className="casino-muted" data-casino-room-preview="">
              Равная ставка на место. Колесо выбирает одного, FocusBet берёт рейк с банка.
            </p>
          </div>
          <button type="button" className="casino-icon-btn casino-create-refresh" onClick={() => void load()} aria-label="Обновить">
            <RefreshCw size={17} />
          </button>
        </div>
        <div className="casino-create-grid">
          <div className="casino-create-field">
            <span>Ставка за место</span>
            <div className="casino-amount-control">
              <input
                type="text"
                inputMode="decimal"
                value={stake}
                onChange={(event) => setStake(event.target.value)}
                aria-label="Сумма ставки"
              />
              <strong>₽</strong>
            </div>
          </div>
          <div className="casino-create-field">
            <span>Количество игроков новой комнаты</span>
            <div className="casino-seat-picker" data-casino-room-seats-pick="">
              {SEAT_CHOICES.filter((count) => count <= (list?.max_seats ?? 10)).map((count) => (
                <button key={count} type="button" className={maxSeats === count ? "is-on" : ""} aria-pressed={maxSeats === count} onClick={() => setMaxSeats(count)}>
                  {count}
                </button>
              ))}
            </div>
          </div>
          <div className="casino-create-field casino-create-field-wide">
            <span>Быстрый выбор</span>
            <div className="casino-choice-row">
              {STAKE_CHIPS.map((amount) => (
                <button key={amount} type="button" className={stakeNumber === amount ? "is-on" : ""} onClick={() => setStake(String(amount))}>
                  {formatRub(amount)}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="casino-create-summary">
          <div><span>Ставка с места</span><strong>{formatRub(stakeNumber)}</strong></div>
          <div><span>Комната</span><strong>до {maxSeats} игроков</strong></div>
          <div><span>При полной игре</span><strong>банк {formatRub(preview.pot)}</strong></div>
        </div>
        <div className="casino-create-actions casino-create-actions-line">
          <button
            type="button"
            className={`casino-btn casino-btn-ghost casino-stake-sort${sortDir === "desc" ? " is-desc" : ""}`}
            data-casino-stake-sort=""
            aria-pressed={sortDir === "desc"}
            onClick={() => setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))}
            title={sortDir === "asc" ? "Сейчас от низких к высоким" : "Сейчас от высоких к низким"}
          >
            {sortDir === "asc" ? "Ставка: сначала низкие" : "Ставка: сначала высокие"}
          </button>
          <button type="button" className="casino-btn casino-btn-primary" disabled={createBusy || !enabled} onClick={() => void onCreate()}>
            <Plus size={17} /> Создать комнату · {formatRub(stakeNumber)}
          </button>
        </div>
      </section>
      <div className="casino-lobby-tables">
        <div className="casino-table-toolbar">
          <h2>Открытые комнаты <span>{rooms.length}</span></h2>
        </div>
        {error ? <p className="casino-duel-error">{error}</p> : null}
        {rooms.length === 0 ? (
          <div className="casino-lobby-empty">
            <h3>Первая комната — ваша</h3>
            <p>Выберите ставку и число мест. Пустые места можно закрыть ботом.</p>
          </div>
        ) : (
          <div className="casino-room-list" data-casino-room-lobby="">
            {rooms.map((row) => (
              <RoomLobbyRow
                key={row.room_id}
                room={row}
                busy={Boolean(busyIds[row.room_id])}
                onJoin={() => void onJoin(row)}
                onLeave={() => void onLeave(row)}
                onAddBot={() => void onAddBot(row)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function RoomLobbyRow({
  room,
  busy,
  onJoin,
  onLeave,
  onAddBot,
}: {
  room: CasinoRoomSnapshot;
  busy?: boolean;
  onJoin: () => void;
  onLeave: () => void;
  onAddBot: () => void;
}) {
  const [opened, setOpened] = useState(false);
  const joinable = room.status === "open" && room.my_seat == null && room.filled < room.seat_count;
  const canDrop = Boolean(room.can_cancel || room.can_leave);
  const spinning = room.status === "locked" || room.status === "settled";
  const counting = room.status === "countdown";
  const expanded = opened || counting || spinning;
  return (
    <article
      className={`casino-room-row${room.my_seat != null ? " is-mine" : ""}${expanded ? " is-open" : ""}`}
      data-casino-room-row={room.room_id}
      onClick={(event) => {
        const target = event.target as HTMLElement | null;
        if (target?.closest("button")) return;
        setOpened(true);
      }}
    >
      <CasinoRoomLiveCanvas
        room={room}
        busy={busy}
        compact
        layout="row"
        forceReel={expanded}
        onJoin={onJoin}
        onAddBot={onAddBot}
      />
      <div className="casino-room-row-bid">
        {joinable ? (
          <button type="button" className="casino-room-row-sit" disabled={busy} onClick={onJoin}>
            Сесть · {formatRub(room.stake_rub)}
          </button>
        ) : (
          <span className="casino-room-row-stake">{formatRub(room.stake_rub)}</span>
        )}
        <span className="casino-room-row-meta">
          {roomStatusLabel(room)}
          {canDrop ? (
            <button type="button" className="casino-room-row-drop" disabled={busy} onClick={onLeave}>
              {room.can_cancel ? "Отменить" : "Выйти"}
            </button>
          ) : null}
        </span>
      </div>
      {counting || (expanded && spinning) ? (
        <CasinoStartCountdown endsAt={room.status === "countdown" ? room.countdown_ends_at : null} />
      ) : null}
    </article>
  );
}

function CasinoFixedRoomPage({ roomId }: { roomId: string }) {
  const { isAuthed, loading } = useSession();
  const navigate = useNavigate();
  const [room, setRoom] = useState<CasinoRoomSnapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const [shift, setShift] = useState(0);
  const [spinEase, setSpinEase] = useState(false);
  const spinningRef = useRef(false);
  const spunRoomRef = useRef<string | null>(null);
  const dataRef = useRef<CasinoRoomSnapshot | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const spinTimer = useRef(0);
  const pendingKick = useRef(false);
  const startSpinRef = useRef<(snap: CasinoRoomSnapshot, winnerId: number) => void>(() => {});

  const applySnap = useCallback((snap: CasinoRoomSnapshot) => {
    setRoom(snap);
    dataRef.current = snap;
  }, []);

  const load = useCallback(async () => {
    if (spinningRef.current) return;
    try {
      const snap = await getCasinoRoom(roomId);
      applySnap(snap);
      setError("");
      if ((snap.status === "locked" || snap.status === "settled") && snap.winner_id != null) {
        startSpinRef.current(snap, snap.winner_id);
      }
    } catch (err) {
      setError(errMessage(err));
    }
  }, [applySnap, roomId]);

  const startSpin = useCallback((snap: CasinoRoomSnapshot, winnerId: number) => {
    if (spinningRef.current) return;
    const key = `${snap.room_id}:${winnerId}:${snap.winner_index ?? ""}`;
    if (spunRoomRef.current === key) return;
    spunRoomRef.current = key;
    spinningRef.current = true;
    pendingKick.current = true;
    setSpinning(true);
    applySnap(snap);
    window.dispatchEvent(new Event(CASINO_BALANCE_HOLD_EVENT));
  }, [applySnap]);
  startSpinRef.current = startSpin;

  useLayoutEffect(() => {
    if (!spinning || !pendingKick.current) return;
    pendingKick.current = false;
    const slot = slotPx();
    const viewport =
      viewportRef.current?.clientWidth ||
      viewportRef.current?.parentElement?.clientWidth ||
      Math.min(window.innerWidth - 24, 640);
    const target = WINNER_INDEX * slot + slot / 2 - viewport / 2;
    if (reduceMotion()) {
      setSpinEase(false);
      setShift(target);
      window.setTimeout(() => {
        spinningRef.current = false;
        setSpinning(false);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
        void load();
      }, 50);
      return;
    }
    setSpinEase(false);
    setShift(0);
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        setSpinEase(true);
        setShift(target);
      });
    });
    window.clearTimeout(spinTimer.current);
    spinTimer.current = window.setTimeout(() => {
      spinningRef.current = false;
      setSpinning(false);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      void load();
    }, SPIN_MS + 200);
  }, [load, spinning]);

  useEffect(() => {
    if (loading) return;
    void load();
  }, [isAuthed, load, loading]);

  useEffect(() => {
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/rooms/events${qs}`, { withCredentials: true });
      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            room_id?: string;
            winner_id?: number;
            winner_index?: number;
            commit_hash?: string;
            server_seed?: string | null;
            hmac_message?: string;
            pot_rub?: number;
            rake_rub?: number;
            payout_rub?: number;
            players?: CasinoRoomPlayer[];
            seat_count?: number;
            stake_rub?: number;
            rake_percent?: number;
          };
          if (payload.room_id && payload.room_id !== roomId) {
            return;
          }
          if (payload.type === "spin" && payload.winner_id != null && payload.players?.length) {
            const frozen = mergeRoomSpinPayload(dataRef.current, payload, roomId);
            startSpin(frozen, payload.winner_id);
            return;
          }
          if (payload.type === "refund") {
            spinningRef.current = false;
            setSpinning(false);
            window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
            void load();
            return;
          }
          if (!spinningRef.current && (payload.type === "join" || payload.type === "leave" || payload.type === "lock" || payload.type === "settled" || payload.type === "countdown" || payload.type === "create")) {
            void load();
          }
        } catch {
          if (!spinningRef.current) void load();
        }
      };
    } catch {
      /* poll only */
    }
    const poll = window.setInterval(() => {
      if (!spinningRef.current) void load();
    }, 2500);
    return () => {
      es?.close();
      window.clearInterval(poll);
      window.clearTimeout(spinTimer.current);
    };
  }, [isAuthed, load, roomId, startSpin]);

  async function run(fn: () => Promise<CasinoRoomSnapshot>) {
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/rooms/${roomId}`);
      return;
    }
    setBusy(true);
    try {
      const snap = await fn();
      applySnap(snap);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      setError("");
      if ((snap.status === "locked" || snap.status === "settled") && snap.winner_id != null) {
        startSpin(snap, snap.winner_id);
      }
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const players = room?.players ?? [];
  const winnerId = room?.winner_id ?? null;
  const reel = useMemo(() => {
    if (!spinning) return [];
    return buildWeightedReel(players, (row) => row.amount_rub || room?.stake_rub || 1, winnerId);
  }, [players, room?.stake_rub, spinning, winnerId]);
  const winner = players.find((row) => row.user_id === winnerId);
  const showReel = spinning;
  const clock = spinning ? "спин" : room ? roomStatusLabel(room) : "—";
  const fairnessHref = room
    ? casinoTo(
        `/casino/fairness?game_type=fixed_room&game_id=${encodeURIComponent(room.room_id)}&commit=${encodeURIComponent(room.commit_hash)}&server_seed=${encodeURIComponent(room.server_seed || "")}&hmac_message=${encodeURIComponent(room.hmac_message)}&modulus=${room.seat_count}&expected_index=${room.winner_index ?? ""}`,
      )
    : casinoTo("/casino/fairness");

  if (!room && !error) return <p className="casino-muted">Загрузка…</p>;
  if (!room) {
    return (
      <div className="casino-rooms">
        <p className="casino-duel-error">{error}</p>
        <Link to={casinoTo(ROOMS_PLAY)}>К комнатам</Link>
      </div>
    );
  }

  return (
    <div className="casino-jackpot casino-rooms" data-casino-room={room.room_id} data-casino-jackpot-phase={spinning ? "spin" : "wait"}>
      <TelegramMainButton
        text={!isAuthed ? "Войти" : room.status === "open" && room.my_seat == null ? `Сесть · ${formatRub(room.stake_rub)}` : ""}
        visible={!isAuthed || (room.status === "open" && room.my_seat == null)}
        onClick={() => {
          if (!isAuthed) goCasinoLogin(navigate, `/casino/rooms/${roomId}`);
          else void run(() => postCasinoRoomJoin(room.room_id));
        }}
      />
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <Link to={casinoTo(ROOMS_PLAY)}>Комнаты</Link>
      </nav>
      <div className="casino-jackpot-head">
        <header className="casino-jackpot-hero">
          <span>Банк</span>
          <strong>{formatRub(room.pot_rub)}</strong>
          <p className="casino-jackpot-meta">
            {clock} · {formatRub(room.stake_rub)} с места
          </p>
        </header>
        <div className="casino-jackpot-bet">
          {room.my_seat != null ? (
            <p className="casino-jackpot-mine">
              Ваша доля {formatRub(room.my_amount_rub || room.stake_rub)} · {(room.my_chance_pct ?? 0).toFixed(1)}%
            </p>
          ) : null}
          {room.status === "open" && room.my_seat == null ? (
            <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void run(() => postCasinoRoomJoin(room.room_id))}>
              Сесть · {formatRub(room.stake_rub)}
            </button>
          ) : null}
          {room.status === "open" && room.can_add_bot ? (
            <button type="button" className="casino-btn" data-casino-room-add-bot="" disabled={busy} onClick={() => void run(() => postCasinoRoomBot(room.room_id))}>
              + бот
            </button>
          ) : null}
          {room.status === "open" && room.can_cancel ? (
            <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => void run(() => postCasinoRoomCancel(room.room_id))}>
              Отменить
            </button>
          ) : null}
          {room.status === "open" && room.can_leave && !room.can_cancel ? (
            <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={() => void run(() => postCasinoRoomLeave(room.room_id))}>
              Выйти
            </button>
          ) : null}
        </div>
      </div>
      <p className="casino-muted casino-jackpot-rules">
        У всех одна ставка. Когда места заняты — колесо. Рейк {room.rake_percent}%.
      </p>
      {error ? <p className="casino-duel-error">{error}</p> : null}

      <div className="casino-table-tile-stage" style={{ minHeight: 96, margin: "8px 0" }}>
      <div
        className={`casino-jackpot-reel is-drama${showReel ? " is-live" : " is-idle"}`}
        ref={viewportRef}
        data-casino-jackpot-reel={showReel ? "spin" : "wait"}
        aria-hidden={!showReel}
      >
        {showReel ? (
          <>
            <div className="casino-jackpot-tick" aria-hidden="true" />
            <div
              className={`casino-jackpot-track${spinEase ? " is-spinning" : ""}`}
              style={{ transform: `translateX(${-shift}px)` }}
            >
              {reel.map((player, index) => (
                <div
                  key={`${player.user_id}-${index}`}
                  className={`casino-jackpot-slot${winnerId === player.user_id && index === WINNER_INDEX && !spinning ? " is-winner" : ""}`}
                >
                  <CasinoPlayerAvatar actor={player} size={48} className="casino-jackpot-avatar-img" />
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
      <CasinoStartCountdown endsAt={room.status === "countdown" ? room.countdown_ends_at : null} />
      </div>

      {winner && !spinning && (room.status === "settled" || room.status === "locked") ? (
        <p className="casino-jackpot-win">
          Победитель {winner.display_name}: {formatRub(room.payout_rub ?? room.pot_rub)}
          {room.rake_rub != null ? ` (дом ${formatRub(room.rake_rub)})` : null}
        </p>
      ) : null}

      {players.length === 0 ? (
        <p className="casino-muted casino-jackpot-empty">Сядьте первым — остальные присоединятся по той же ставке.</p>
      ) : (
        <>
          <div className="casino-jackpot-shares" aria-hidden="true">
            {players.map((player, index) => (
              <i
                key={`${player.user_id}-${player.seat_no}`}
                style={{
                  width: `${Math.min(100, Math.max(0, player.chance_pct ?? 0))}%`,
                  background: shareColor(index),
                }}
              />
            ))}
          </div>
          <ul className="casino-jackpot-list">
            {players.map((player, index) => (
              <li key={`${player.user_id}-${player.seat_no}`} className={winnerId === player.user_id && !spinning ? "is-winner" : undefined}>
                <i className="casino-jackpot-swatch" style={{ background: shareColor(index) }} aria-hidden="true" />
                <CasinoPlayerChip
                  actor={player}
                  size={32}
                  linked={(player.participant_kind || "player") !== "bot" && player.user_id !== 0}
                />
                <span className="casino-jackpot-list-meta">
                  <strong>{formatRub(player.amount_rub ?? room.stake_rub)}</strong>
                  <em>{(player.chance_pct ?? 0).toFixed(1)}%</em>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="casino-muted casino-jackpot-fair">
        <span>
          Хеш:{" "}
          <code title={room.commit_hash || undefined}>{shortHash(room.commit_hash || "")}</code>
        </span>
        {room.server_seed ? (
          <span>
            {" "}
            · сид <code>{shortHash(room.server_seed, 8)}</code>
          </span>
        ) : (
          <span> · сид после розыгрыша</span>
        )}
        {" · "}
        <Link to={fairnessHref}>Проверить</Link>
      </p>
    </div>
  );
}
