import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  getCasinoJackpot,
  postCasinoJackpotBet,
  type CasinoJackpotPlayer,
  type CasinoJackpotSnapshot,
} from "@/lib/public";
import { API_BASE, getToken } from "@/lib/api";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CASINO_BALANCE_EVENT, CASINO_BALANCE_HOLD_EVENT } from "./gameCatalog";
import { useWalletScopeRefresh } from "./walletScope";
import { CasinoPlayerAvatar, CasinoPlayerChip } from "./CasinoPlayerChip";
import { WEIGHTED_REEL_SPIN_MS, WEIGHTED_REEL_WINNER_INDEX, buildWeightedReel } from "./weightedReel";

const SLOT_DESKTOP_PX = 72;
const SLOT_MOBILE_PX = 56;
const WINNER_INDEX = WEIGHTED_REEL_WINNER_INDEX;
const SPIN_MS = WEIGHTED_REEL_SPIN_MS;
const JACKPOT_PLAY = "/casino/play/jackpot?mode=players";
const JACKPOT_CHIPS = [100, 500, 1000, 5000];
const SHARE_LIGHTS = [86, 72, 58, 46, 38, 28, 20, 14];

function slotPx(): number {
  try {
    if (window.matchMedia("(max-width: 767px)").matches) return SLOT_MOBILE_PX;
  } catch {
    /* SSR / old */
  }
  return SLOT_DESKTOP_PX;
}

function shareColor(index: number): string {
  return `hsl(0 0% ${SHARE_LIGHTS[index % SHARE_LIGHTS.length]}%)`;
}

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
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

function buildReel(players: CasinoJackpotPlayer[], winnerId: number | null): CasinoJackpotPlayer[] {
  return buildWeightedReel(players, (row) => row.amount_rub, winnerId);
}

function Avatar({ player, size = 48 }: { player: CasinoJackpotPlayer; size?: number }) {
  return <CasinoPlayerAvatar actor={player} size={size} className="casino-jackpot-avatar-img" />;
}

export function CasinoJackpot({ embedded = false }: { embedded?: boolean }) {
  const { user, isAuthed, loading } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<CasinoJackpotSnapshot | null>(null);
  const [error, setError] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [spinning, setSpinning] = useState(false);
  const [shift, setShift] = useState(0);
  const [spinEase, setSpinEase] = useState(false);
  const spinningRef = useRef(false);
  const spunRoundRef = useRef<string | null>(null);
  const dataRef = useRef<CasinoJackpotSnapshot | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const spinTimer = useRef<number>(0);
  const finishSpinRef = useRef<() => void>(() => {});
  const seededBet = useRef(false);
  const pendingKick = useRef(false);
  const startSpinRef = useRef<(snap: CasinoJackpotSnapshot, winnerId: number) => void>(() => {});

  const applySnap = useCallback((snap: CasinoJackpotSnapshot) => {
    if (spinningRef.current && snap.status === "open" && (snap.player_count ?? 0) === 0) {
      return;
    }
    setData(snap);
    dataRef.current = snap;
    if (!seededBet.current && snap.min_bet_rub) {
      seededBet.current = true;
      setAmount(String(snap.min_bet_rub));
    }
  }, []);

  const load = useCallback(async () => {
    if (spinningRef.current) return;
    try {
      const snap = await getCasinoJackpot();
      applySnap(snap);
      setError("");
      if ((snap.status === "locked" || snap.status === "settled") && snap.winner_id) {
        startSpinRef.current(snap, snap.winner_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить джекпот");
    }
  }, [applySnap]);

  useWalletScopeRefresh(load);

  const startSpin = useCallback((snap: CasinoJackpotSnapshot, winnerId: number) => {
    if (spinningRef.current) return;
    if (spunRoundRef.current === snap.round_id) return;
    spunRoundRef.current = snap.round_id;
    spinningRef.current = true;
    pendingKick.current = true;
    setSpinning(true);
    setData(snap);
    dataRef.current = snap;
    window.dispatchEvent(new Event(CASINO_BALANCE_HOLD_EVENT));
  }, []);
  startSpinRef.current = startSpin;

  const finishSpin = useCallback(() => {
    window.clearTimeout(spinTimer.current);
    if (!spinningRef.current) return;
    spinningRef.current = false;
    setSpinning(false);
    setSpinEase(false);
    window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    void load();
  }, [load]);
  finishSpinRef.current = finishSpin;

  const skipSpin = useCallback(() => {
    if (!spinningRef.current) return;
    const slot = slotPx();
    const viewport =
      viewportRef.current?.clientWidth ||
      viewportRef.current?.parentElement?.clientWidth ||
      Math.min(window.innerWidth - 24, 640);
    const target = WINNER_INDEX * slot + slot / 2 - viewport / 2;
    setSpinEase(false);
    setShift(target);
    finishSpin();
  }, [finishSpin]);

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
      finishSpinRef.current();
    }, SPIN_MS + 200);
  }, [load, spinning]);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, JACKPOT_PLAY);
      return;
    }
    void load();
  }, [isAuthed, load, loading, navigate]);

  useEffect(() => {
    if (!isAuthed) return;
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/jackpot/events${qs}`, { withCredentials: true });
      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            round_id?: string;
            winner_id?: number;
            winning_ticket?: number;
            roll?: string;
            commit_hash?: string;
            pot_rub?: number;
            rake_rub?: number;
            payout_rub?: number;
            total_tickets?: number;
            players?: CasinoJackpotPlayer[];
          };
          if (payload.type === "spin" && payload.winner_id && payload.players?.length) {
            const live = dataRef.current;
            const frozen: CasinoJackpotSnapshot = {
              success: true,
              round_id: String(payload.round_id || live?.round_id || ""),
              status: "locked",
              commit_hash: String(payload.commit_hash || live?.commit_hash || ""),
              roll: payload.roll ?? null,
              closes_at: null,
              pot_rub: Number(payload.pot_rub) || live?.pot_rub || 0,
              rake_percent: live?.rake_percent || 5,
              rake_rub: payload.rake_rub ?? null,
              payout_rub: payload.payout_rub ?? null,
              winner_id: payload.winner_id,
              winning_ticket: payload.winning_ticket ?? null,
              player_count: payload.players.length,
              max_players: live?.max_players || 30,
              collect_seconds: live?.collect_seconds || 300,
              min_bet_rub: live?.min_bet_rub || 10,
              max_bet_rub: live?.max_bet_rub || 100000,
              enabled: true,
              players: payload.players,
              total_tickets: payload.total_tickets || 0,
              my_amount_rub: live?.my_amount_rub || 0,
              my_chance_pct: live?.my_chance_pct || 0,
            };
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
          if (!spinningRef.current && (payload.type === "bet" || payload.type === "settled" || payload.type === "lock")) {
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
    }, 2000);
    return () => {
      es?.close();
      window.clearInterval(poll);
      window.clearTimeout(spinTimer.current);
    };
  }, [isAuthed, load, startSpin]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(tick);
  }, []);

  const players = useMemo(() => {
    const rows = data?.players ?? [];
    return [...rows].sort((a, b) => b.amount_rub - a.amount_rub || a.user_id - b.user_id);
  }, [data?.players]);
  const winnerId = data?.winner_id ?? null;
  const reel = useMemo(() => {
    if (!spinning) return [];
    return buildReel(players, winnerId);
  }, [players, spinning, winnerId]);

  const remainMs = (() => {
    if (!data?.closes_at) return null;
    const end = Date.parse(data.closes_at);
    if (!Number.isFinite(end)) return null;
    return Math.max(0, end - now);
  })();

  const clock = spinning
    ? "спин"
    : remainMs == null
      ? players.length
        ? "ждём"
        : "с 1-й ставки"
      : `${String(Math.floor(remainMs / 60000)).padStart(2, "0")}:${String(Math.floor((remainMs % 60000) / 1000)).padStart(2, "0")}`;

  async function bet() {
    if (!isAuthed) {
      goCasinoLogin(navigate, JACKPOT_PLAY);
      return;
    }
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setError("Укажите ставку");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const snap = await postCasinoJackpotBet(value);
      applySnap(snap);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      if ((snap.status === "locked" || snap.status === "settled") && snap.winner_id) {
        startSpin(snap, snap.winner_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ставка не прошла");
    } finally {
      setBusy(false);
    }
  }

  const winner = players.find((row) => row.user_id === winnerId);
  const fairnessHref = data?.roll
    ? casinoTo(
        `/casino/fairness?game_type=jackpot&game_id=${encodeURIComponent(data.round_id)}&commit=${encodeURIComponent(data.commit_hash)}&server_seed=${encodeURIComponent(data.roll)}&client_seed=focuspay&nonce=0&total_tickets=${data.total_tickets}&expected_ticket=${data.winning_ticket ?? ""}`,
      )
    : casinoTo("/casino/fairness");
  const showReel = spinning;
  const minBet = data?.min_bet_rub || 1;

  return (
    <div className="casino-jackpot" data-casino-jackpot="1" data-casino-jackpot-phase={spinning ? "spin" : "wait"}>
      {embedded ? null : (
        <nav className="casino-crumb" aria-label="Навигация">
          <Link to={casinoTo("/casino")}>Лобби</Link>
          <span className="casino-crumb-sep" aria-hidden>
            /
          </span>
          <span>Джекпот</span>
        </nav>
      )}
      <div className="casino-jackpot-head">
        <header className="casino-jackpot-hero">
          <span>Банк</span>
          <strong>{formatRub(data?.pot_rub ?? 0)}</strong>
          <p className="casino-jackpot-meta">
            {clock} · {data ? `${data.player_count}/${data.max_players}` : "—"}
          </p>
        </header>
        <form
          className="casino-jackpot-bet"
          onSubmit={(event) => {
            event.preventDefault();
            void bet();
          }}
        >
          {data?.my_amount_rub ? (
            <p className="casino-jackpot-mine">
              Ваша доля {formatRub(data.my_amount_rub)} · {data.my_chance_pct.toFixed(1)}%
            </p>
          ) : null}
          <label className="casino-jackpot-bet-field">
            <span>Ставка, ₽</span>
            <span className="casino-jackpot-bet-row">
              <input
                type="number"
                min={minBet}
                max={data?.max_bet_rub || undefined}
                step="1"
                inputMode="decimal"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                disabled={busy || spinning || data?.enabled === false}
                aria-label="Ставка, рубли"
              />
              <button type="submit" className="casino-btn casino-btn-primary" disabled={busy || spinning || data?.enabled === false}>
                {data?.my_amount_rub ? "Докинуть" : "Поставить"}
              </button>
            </span>
            <span className="casino-jackpot-chips" role="group" aria-label="Быстрый выбор суммы">
              {JACKPOT_CHIPS.filter((chip) => chip >= (data?.min_bet_rub || 1) && chip <= (data?.max_bet_rub || chip)).map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className={Number(amount) === chip ? "is-on" : ""}
                  aria-pressed={Number(amount) === chip}
                  disabled={busy || spinning || data?.enabled === false}
                  onClick={() => setAmount(String(chip))}
                >
                  {chip}
                </button>
              ))}
            </span>
          </label>
        </form>
      </div>
      <p className="casino-muted casino-jackpot-rules">
        Шанс = доля в банке. Докинуть можно, выйти нельзя. Рейк {data ? `${data.rake_percent}%` : "5%"}.
      </p>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {data && !data.enabled ? <p className="casino-muted">Джекпот выключен в настройках.</p> : null}

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
                  <Avatar player={player} />
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
      {spinning ? (
        <button type="button" className="casino-btn casino-btn-ghost casino-jackpot-skip" data-casino-jackpot-skip="" onClick={skipSpin}>
          Пропустить анимацию
        </button>
      ) : null}

      {winner && !spinning && (data?.status === "settled" || data?.status === "locked" || data?.status === "refunded") ? (
        <section className="casino-jackpot-result" data-casino-jackpot-result="">
          <h3>
            {data?.status === "refunded"
              ? "Ставка возвращена"
              : user?.id != null && winnerId === user.id
                ? "Вы победили"
                : `Победитель: ${winner.display_name}`}
          </h3>
          <p>
            {data?.winning_ticket != null
              ? `Билет ${data.winning_ticket} из ${data.total_tickets}`
              : "Итог раунда"}
          </p>
          <strong>{formatRub(data?.payout_rub ?? data?.pot_rub ?? 0)}</strong>
          {data?.status !== "refunded" && data?.rake_rub != null ? <span>После рейка {formatRub(data.rake_rub)}</span> : null}
        </section>
      ) : null}

      {players.length === 0 ? (
        <p className="casino-muted casino-jackpot-empty">Первая ставка запускает таймер.</p>
      ) : (
        <>
          <div className="casino-jackpot-shares" aria-hidden="true">
            {players.map((player, index) => (
              <i
                key={player.user_id}
                style={{
                  width: `${Math.min(100, Math.max(0, player.chance_pct))}%`,
                  background: shareColor(index),
                }}
              />
            ))}
          </div>
          <ul className="casino-jackpot-list">
            {players.map((player, index) => (
              <li key={player.user_id} className={winnerId === player.user_id && !spinning ? "is-winner" : undefined}>
                <i className="casino-jackpot-swatch" style={{ background: shareColor(index) }} aria-hidden="true" />
                <CasinoPlayerChip actor={player} size={32} />
                <span className="casino-jackpot-list-meta">
                  <strong>{formatRub(player.amount_rub)}</strong>
                  <em>{player.chance_pct.toFixed(1)}%</em>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="casino-muted casino-jackpot-fair">
        <span>
          Хеш:{" "}
          <code title={data?.commit_hash || undefined}>{shortHash(data?.commit_hash || "")}</code>
        </span>
        {data?.roll ? (
          <span>
            {" "}
            · roll <code>{shortHash(data.roll, 8)}</code>
          </span>
        ) : (
          <span> · roll на спине</span>
        )}
        {" · "}
        <Link to={fairnessHref}>Проверить</Link>
      </p>
    </div>
  );
}
