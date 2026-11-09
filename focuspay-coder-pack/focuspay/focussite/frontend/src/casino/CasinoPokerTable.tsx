import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  actCasinoPoker,
  getCasinoPokerTable,
  leaveCasinoPoker,
  sitCasinoPoker,
  type CasinoPokerSnapshot,
} from "@/lib/public";
import { API_BASE, getToken } from "@/lib/api";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";
import { prefersCasinoReducedMotion } from "./CasinoDice";
import { CasinoPlayingCard } from "./CasinoPlayingCard";

const BOARD_SLOTS = 5;
const HOLE_SLOTS = 2;

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function FeltBoard({ board }: { board: string[] }) {
  const skipDeal = prefersCasinoReducedMotion();
  return (
    <div className="casino-felt-board casino-poker-board" data-casino-felt-board="">
      {Array.from({ length: BOARD_SLOTS }, (_, index) => {
        const code = board[index];
        if (!code) {
          return <span key={`slot-${index}`} className="casino-felt-slot" data-casino-felt-slot="" />;
        }
        return (
          <CasinoPlayingCard key={`${code}-${index}`} code={code} compact dealing={!skipDeal} />
        );
      })}
    </div>
  );
}

function FeltHole({
  hole,
  occupied,
  inHand,
  folded,
}: {
  hole?: string[] | null;
  occupied: boolean;
  inHand: boolean;
  folded?: boolean;
}) {
  if (!occupied || !inHand) return null;
  const skipDeal = prefersCasinoReducedMotion();
  const faces = (hole ?? []).map((card) => String(card).trim()).filter(Boolean);
  return (
    <div className={`casino-felt-hole casino-poker-hole${folded ? " is-muck" : ""}`} data-casino-felt-hole="">
      {faces.length > 0
        ? faces.map((code, index) => (
            <CasinoPlayingCard key={`${code}-${index}`} code={code} compact dealing={!skipDeal} />
          ))
        : Array.from({ length: HOLE_SLOTS }, (_, index) => (
            <CasinoPlayingCard key={`back-${index}`} faceDown compact dealing={!skipDeal} />
          ))}
      {folded ? <span className="casino-felt-fold">фолд</span> : null}
    </div>
  );
}

export function CasinoPokerTable() {
  const { tableId } = useParams();
  const navigate = useNavigate();
  const { isAuthed, loading } = useSession();
  const [room, setRoom] = useState<CasinoPokerSnapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [buyIn, setBuyIn] = useState("");
  const [raiseTo, setRaiseTo] = useState("");
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    if (!tableId) return;
    try {
      const snap = await getCasinoPokerTable(tableId);
      setRoom(snap);
      setError("");
      setBuyIn((current) => current || String(snap.min_buyin_rub));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Стол не найден");
    }
  }, [tableId]);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/poker/${tableId || ""}`);
      return;
    }
    void load();
  }, [isAuthed, load, loading, navigate, tableId]);

  useEffect(() => {
    if (!tableId || !isAuthed) return;
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/poker/tables/${encodeURIComponent(tableId)}/events${qs}`, {
        withCredentials: true,
      });
      es.onmessage = () => {
        void load();
      };
    } catch {
      /* poll only */
    }
    const poll = window.setInterval(() => void load(), 2000);
    return () => {
      es?.close();
      window.clearInterval(poll);
    };
  }, [isAuthed, load, tableId]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  const legal = room?.hand?.legal ?? room?.legal ?? { actions: [] as string[] };
  const minRaise = Number(legal.min_raise_to) || 0;
  const maxRaise = Number(legal.max_raise_to) || minRaise;

  useEffect(() => {
    if (!legal.actions?.includes("raise")) return;
    setRaiseTo((current) => {
      const parsed = Number(current);
      if (Number.isFinite(parsed) && parsed >= minRaise && parsed <= maxRaise) return current;
      return String(minRaise);
    });
  }, [legal.actions, minRaise, maxRaise]);

  const canAct = Boolean(room?.you_seat && legal.actions?.length);
  const remainingMs = useMemo(() => {
    const iso = room?.hand?.action_deadline_at;
    if (!iso) return null;
    return Math.max(0, Date.parse(iso) - now);
  }, [now, room?.hand?.action_deadline_at]);

  async function sit(seatNo: number) {
    if (!tableId) return;
    setBusy(true);
    try {
      const snap = await sitCasinoPoker(tableId, seatNo, Number(buyIn));
      setRoom(snap);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не сели");
    } finally {
      setBusy(false);
    }
  }

  async function leave() {
    if (!tableId) return;
    setBusy(true);
    try {
      const snap = await leaveCasinoPoker(tableId);
      setRoom(snap);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не встали");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: string, amount?: number) {
    if (!tableId || !room) return;
    setBusy(true);
    try {
      const snap = await actCasinoPoker(tableId, {
        action,
        amount_rub: amount,
        expected_version: room.state_version,
      });
      setRoom(snap);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ход не принят");
      void load();
    } finally {
      setBusy(false);
    }
  }

  const handSeats = new Map((room?.hand?.seats ?? []).map((seat) => [seat.seat_no, seat]));
  const fairnessBoard = room?.fairness?.board ?? room?.hand?.board ?? [];
  const fairnessHref = room?.fairness?.server_seed
    ? casinoTo(
        `/casino/fairness?game_type=holdem&game_id=${encodeURIComponent(room.fairness.hand_id)}&commit=${encodeURIComponent(room.fairness.commit)}&server_seed=${encodeURIComponent(room.fairness.server_seed)}&client_seed=${encodeURIComponent(room.fairness.client_seed)}&nonce=${room.fairness.nonce}${fairnessBoard.length ? `&expected_cards=${encodeURIComponent(fairnessBoard.join(" "))}` : ""}`,
      )
    : "";

  return (
    <div className="casino-poker-table" data-casino-poker-table="1">
      <p className="casino-muted">
        <Link to={casinoTo("/casino/play/holdem?mode=players")}>← К столам</Link>
      </p>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {room ? (
        <>
          <h1>
            {formatRub(room.small_blind_rub)}/{formatRub(room.big_blind_rub)} · банк{" "}
            {formatRub(room.hand?.pot_rub ?? 0)}
          </h1>
          <p className="casino-muted">
            Бай-ин {formatRub(room.min_buyin_rub)}–{formatRub(room.max_buyin_rub)}
            {remainingMs != null ? ` · ход ${Math.ceil(remainingMs / 1000)} с` : ""}
            {room.hand ? ` · ${room.hand.street}` : " · ожидание игроков"}
          </p>
          <div className="casino-poker-felt casino-felt" data-casino-felt="1">
            <FeltBoard board={room.hand?.board ?? []} />
            <div className="casino-poker-seats casino-felt-seats" data-seats={room.max_seats}>
              {room.seats.map((seat) => {
                const live = handSeats.get(seat.seat_no);
                const active = room.hand?.to_act === seat.seat_no;
                const folded = Boolean(live?.folded);
                return (
                  <div
                    key={seat.seat_no}
                    className={`casino-poker-seat casino-felt-seat${active ? " is-active" : ""}${folded ? " is-folded" : ""}`}
                    data-seat={seat.seat_no}
                  >
                    <p>
                      {seat.label}
                      {room.button_seat === seat.seat_no ? " · D" : ""}
                    </p>
                    {seat.occupied ? (
                      <>
                        <p>{formatRub(live?.stack_rub ?? seat.stack_rub)}</p>
                        {live?.street_bet_rub ? <p className="casino-muted">ставка {formatRub(live.street_bet_rub)}</p> : null}
                        <FeltHole
                          hole={live?.hole}
                          occupied={seat.occupied}
                          inHand={Boolean(room.hand)}
                          folded={folded}
                        />
                      </>
                    ) : (
                      <button type="button" className="casino-btn" disabled={busy || Boolean(room.you_seat)} onClick={() => void sit(seat.seat_no)}>
                        Сесть
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          {!room.you_seat ? (
            <label className="casino-poker-buyin">
              Бай-ин
              <input type="number" min={room.min_buyin_rub} max={room.max_buyin_rub} value={buyIn} onChange={(event) => setBuyIn(event.target.value)} />
            </label>
          ) : (
            <button type="button" className="casino-btn" disabled={busy} onClick={() => void leave()}>
              Встать со стола
            </button>
          )}
          {canAct ? (
            <div className="casino-poker-actions">
              {legal.actions.includes("fold") ? (
                <button type="button" className="casino-btn" disabled={busy} onClick={() => void act("fold")}>
                  Фолд
                </button>
              ) : null}
              {legal.actions.includes("check") ? (
                <button type="button" className="casino-btn" disabled={busy} onClick={() => void act("check")}>
                  Чек
                </button>
              ) : null}
              {legal.actions.includes("call") ? (
                <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void act("call")}>
                  Колл {formatRub(Number(legal.call_rub) || 0)}
                </button>
              ) : null}
              {legal.actions.includes("raise") ? (
                <label className="casino-poker-raise">
                  <span>Рейз до {formatRub(Number(raiseTo) || minRaise)}</span>
                  <input
                    type="range"
                    min={minRaise}
                    max={maxRaise}
                    step="1"
                    value={raiseTo || String(minRaise)}
                    onChange={(event) => setRaiseTo(event.target.value)}
                  />
                  <input
                    type="number"
                    min={minRaise}
                    max={maxRaise}
                    value={raiseTo || String(minRaise)}
                    onChange={(event) => setRaiseTo(event.target.value)}
                  />
                  <button
                    type="button"
                    className="casino-btn"
                    disabled={busy}
                    onClick={() => void act("raise", Number(raiseTo || minRaise))}
                  >
                    Рейз
                  </button>
                </label>
              ) : null}
              {legal.actions.includes("all_in") ? (
                <button type="button" className="casino-btn" disabled={busy} onClick={() => void act("all_in")}>
                  Олл-ин
                </button>
              ) : null}
            </div>
          ) : null}
          {room.hand?.winners?.length ? (
            <p>
              Итог:{" "}
              {room.hand.winners.map((row) => `место ${row.seat_no} +${row.amount}${row.hand ? ` (${row.hand})` : ""}`).join(" · ")}
            </p>
          ) : null}
          {room.fairness ? (
            <p className="casino-muted">
              Коммит {room.fairness.commit.slice(0, 12)}…{" "}
              {fairnessHref ? (
                <Link to={fairnessHref}>проверить честность</Link>
              ) : (
                "сид после вскрытия"
              )}
            </p>
          ) : null}
        </>
      ) : (
        <p className="casino-muted">Загрузка стола…</p>
      )}
    </div>
  );
}
