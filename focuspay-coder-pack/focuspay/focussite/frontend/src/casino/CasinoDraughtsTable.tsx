import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { API_BASE, getToken } from "@/lib/api";
import {
  actDraughtsTable,
  answerDraughtsDraw,
  getDraughtsTable,
  joinDraughtsTable,
  leaveDraughtsTable,
  offerDraughtsDraw,
  type DraughtsMove,
  type DraughtsSnapshot,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";

const FILES = "abcdefgh";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function squareName(x: number, y: number, side: "white" | "black"): string {
  if (side === "black") return `${FILES[7 - x]}${y + 1}`;
  return `${FILES[x]}${8 - y}`;
}

function isDark(name: string): boolean {
  const file = FILES.indexOf(name[0] ?? "");
  const rank = Number(name.slice(1));
  return (file + rank) % 2 === 1;
}

export function DraughtsBoard({
  pieces,
  side,
  origins,
  targets,
  selected,
  interactive,
  onSquare,
}: {
  pieces: DraughtsSnapshot["pieces"];
  side: "white" | "black";
  origins: Set<string>;
  targets: Set<string>;
  selected: string;
  interactive: boolean;
  onSquare: (name: string) => void;
}) {
  const bySquare = new Map(pieces.map((piece) => [piece.square, piece]));
  return (
    <div className="casino-draughts-board" data-draughts-orientation={side}>
      {Array.from({ length: 64 }, (_, index) => {
        const x = index % 8;
        const y = Math.floor(index / 8);
        const name = squareName(x, y, side);
        const dark = isDark(name);
        const piece = bySquare.get(name);
        const hot = selected === name || targets.has(name) || (!selected && origins.has(name));
        return (
          <div
            key={name}
            role="button"
            className={`casino-draughts-square${dark ? " is-dark" : " is-light"}${hot ? " is-hot" : ""}`}
            data-square={name}
            onClick={() => interactive && dark && onSquare(name)}
          >
            {piece ? (
              <span className={`casino-draughts-piece is-${piece.side}${piece.kind === "king" ? " is-king" : ""}`}>
                {piece.kind === "king" ? "Д" : ""}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function reasonText(reason: string): string {
  if (reason === "timeout") return "Время хода вышло";
  if (reason === "resign") return "Сдача";
  if (reason === "6.1.7") return "Нет ходов";
  if (reason === "6.1.8.1") return "Согласились на ничью";
  if (reason === "threefold") return "Троекратное повторение";
  if (reason.startsWith("6.1.8")) return `Ничья по ${reason}`;
  return reason;
}

export function CasinoDraughtsTable() {
  const { tableId = "" } = useParams();
  const navigate = useNavigate();
  const { isAuthed, loading } = useSession();
  const [snap, setSnap] = useState<DraughtsSnapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState("");
  const [choices, setChoices] = useState<DraughtsMove[]>([]);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    if (!tableId) return;
    try {
      const next = await getDraughtsTable(tableId);
      setSnap(next);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Стол не открылся");
    }
  }, [tableId]);

  useEffect(() => {
    if (loading) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/draughts/${tableId}`);
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
      es = new EventSource(`${API_BASE}/user/casino/draughts/tables/${encodeURIComponent(tableId)}/events${qs}`, {
        withCredentials: true,
      });
      es.onmessage = () => {
        void load();
      };
    } catch {
      /* poll only */
    }
    const poll = window.setInterval(() => void load(), 2000);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      es?.close();
      window.clearInterval(poll);
      window.clearInterval(clock);
    };
  }, [isAuthed, load, tableId]);

  useEffect(() => {
    setSelected("");
    setChoices([]);
  }, [snap?.state_version, snap?.your_turn]);

  const side = snap?.your_side === "black" ? "black" : "white";
  const legal = snap?.your_turn ? snap.legal_moves : [];
  const origins = useMemo(() => new Set(legal.map((move) => move.origin)), [legal]);
  const fromHere = selected ? legal.filter((move) => move.origin === selected) : [];
  const targets = useMemo(() => new Set(fromHere.map((move) => move.destination)), [fromHere]);

  async function run(task: () => Promise<DraughtsSnapshot>) {
    setBusy(true);
    setError("");
    try {
      const next = await task();
      setSnap(next);
      setChoices([]);
      setSelected("");
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вышло");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function play(move: DraughtsMove) {
    if (!snap) return;
    setBusy(true);
    setError("");
    try {
      let next: DraughtsSnapshot;
      try {
        next = await actDraughtsTable(tableId, { notation: move.notation, expected_version: snap.state_version });
      } catch (err) {
        const message = err instanceof Error ? err.message : "";
        if (!message.includes("обновился")) throw err;
        const fresh = await getDraughtsTable(tableId);
        if (!fresh.your_turn || !fresh.legal_moves.some((item) => item.notation === move.notation)) {
          setSnap(fresh);
          throw err;
        }
        next = await actDraughtsTable(tableId, { notation: move.notation, expected_version: fresh.state_version });
      }
      setSnap(next);
      setChoices([]);
      setSelected("");
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вышло");
      await load();
    } finally {
      setBusy(false);
    }
  }

  function onSquare(name: string) {
    if (!snap?.your_turn || busy || !isDark(name)) return;
    if (selected && targets.has(name)) {
      const matches = fromHere.filter((move) => move.destination === name);
      if (matches.length === 1) {
        play(matches[0]);
        return;
      }
      setChoices(matches);
      return;
    }
    if (origins.has(name)) {
      setSelected(name);
      setChoices([]);
    }
  }

  const leftSeconds =
    snap?.deadline_at && snap.status === "running"
      ? Math.max(0, Math.ceil((new Date(snap.deadline_at).getTime() - now) / 1000))
      : null;
  const resultLine = !snap?.result
    ? ""
    : snap.result === "draw"
      ? `Ничья. ${reasonText(snap.reason)}. Возврат ${formatRub(snap.your_payout_rub ?? snap.stake_rub)}.`
      : `${snap.result === "white" ? "Белые" : "Чёрные"} выиграли. ${reasonText(snap.reason)}.${
          snap.your_payout_rub != null ? ` Вам ${formatRub(snap.your_payout_rub)}.` : ""
        }`;

  return (
    <div className="casino-play" data-casino-draughts="table">
      <p className="casino-muted">
        <Link to={casinoTo("/casino/play/russian_draughts")}>← К столам</Link>
      </p>
      <h1>Русские шашки</h1>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {snap ? (
        <>
          <p className="casino-muted">
            Ставка {formatRub(snap.stake_rub)}. Вы: {snap.your_side === "white" ? "белые" : snap.your_side === "black" ? "чёрные" : "зритель"}.
            Рейк {snap.rake_percent}%{snap.rake_cap_rub > 0 ? `, потолок ${formatRub(snap.rake_cap_rub)}` : ""}.
          </p>
          {leftSeconds != null && snap.your_turn ? <p className="casino-muted">Ход ещё {leftSeconds} с, потом сдача.</p> : null}
          <DraughtsBoard
            pieces={snap.pieces}
            side={side}
            origins={origins}
            targets={targets}
            selected={selected}
            interactive={Boolean(snap.your_turn) && !busy}
            onSquare={onSquare}
          />
          {snap.your_turn && legal.length ? (
            <div className="casino-draughts-moves">
              {(choices.length > 1 ? choices : legal).map((move) => (
                <button key={move.notation} type="button" className="casino-btn" disabled={busy} onClick={() => play(move)}>
                  {move.notation}
                </button>
              ))}
            </div>
          ) : null}
          {snap.status === "running" && snap.your_turn ? <p className="casino-muted">Ваш ход. Нажмите шашку и поле, или ход в списке.</p> : null}
          {snap.moves.length ? <p className="casino-muted">Ходы: {snap.moves.join(", ")}</p> : null}
          {resultLine ? (
            <p>
              <strong>{resultLine}</strong>
            </p>
          ) : null}
          {snap.status === "waiting" ? (
            <p className="casino-muted">
              Ход появится у белых, когда сядут чёрные.{snap.your_side === "white" ? " Отмена вернёт ставку." : ""}
            </p>
          ) : null}
          {snap.status === "waiting" && !snap.your_side ? (
            <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void run(() => joinDraughtsTable(tableId))}>
              Сесть чёрными за {formatRub(snap.stake_rub)}
            </button>
          ) : null}
          {snap.status === "running" && snap.your_side && !snap.your_turn ? <p className="casino-muted">Ход соперника.</p> : null}
          {snap.can_offer_draw ? (
            <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => offerDraughtsDraw(tableId))}>
              Предложить ничью
            </button>
          ) : null}
          {snap.draw_offer ? (
            <div className="casino-duel-toolbar">
              <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void run(() => answerDraughtsDraw(tableId, true))}>
                Согласиться на ничью
              </button>
              <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => answerDraughtsDraw(tableId, false))}>
                Отказать
              </button>
            </div>
          ) : null}
          {snap.your_side && (snap.status === "waiting" || snap.status === "running") ? (
            <button type="button" className="casino-btn" disabled={busy} onClick={() => void run(() => leaveDraughtsTable(tableId))}>
              {snap.status === "waiting" ? "Отменить стол" : "Сдаться"}
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
