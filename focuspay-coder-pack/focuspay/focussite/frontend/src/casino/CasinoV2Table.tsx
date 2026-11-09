import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  addCasinoV2Bot,
  cancelCasinoV2Table,
  chooseCasinoV2Draw,
  getCasinoV2Table,
  hitCasinoV2Table,
  leaveCasinoV2Table,
  rollCasinoV2Table,
  standCasinoV2Table,
  startCasinoV2Table,
  type CasinoV2TableView,
} from "@/lib/public";
import { useSession } from "@/lib/session";
import { CreditCard, Dices, Spade } from "lucide-react";
import { prefersCasinoReducedMotion } from "./CasinoDice";
import { baccaratDealingLabel } from "./baccaratStreets";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoV2CompactPlay } from "./CasinoV2CompactPlay";
import { CasinoRoundResult } from "./CasinoRoundResult";
import { TelegramMainButton } from "./TelegramMainButton";
import { useBaccaratStreets } from "./useBaccaratStreets";
import { useV2RoundNotice } from "./useV2RoundNotice";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";
import {
  formatCasinoRub,
  v2LobbyPath,
  v2MyRoundResult,
  v2SeatPayout,
  v2StatusLabel,
  v2WinnerSeatNos,
} from "./v2RoundResult";

function formatRub(value: string | number): string {
  return formatCasinoRub(value);
}

export function CasinoV2Table() {
  const { tableId } = useParams();
  const navigate = useNavigate();
  const { isAuthed } = useSession();
  const [table, setTable] = useState<CasinoV2TableView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const actionPending = useRef(false);
  function acceptTable(next: CasinoV2TableView) {
    setTable((current) => current?.table_id === next.table_id && current.state_version > next.state_version ? current : next);
  }
  const [rollingSeat, setRollingSeat] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const streets = useBaccaratStreets(table);

  useEffect(() => {
    if (!tableId) return;
    const id = tableId;
    let cancelled = false;
    async function load() {
      try {
        const next = await getCasinoV2Table(id);
        if (!cancelled) {
          acceptTable(next);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Стол не найден");
      }
    }
    void load();
    const poll = window.setInterval(() => void load(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [tableId]);

  useV2RoundNotice(table);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(tick);
  }, []);

  const deadlineMs = table?.roll_deadline_at ? Date.parse(table.roll_deadline_at) : NaN;
  const remainSec = Number.isFinite(deadlineMs) ? Math.max(0, Math.ceil((deadlineMs - now) / 1000)) : null;
  const canRoll = Boolean(table?.can_roll);
  const canChooseDraw = Boolean(table?.can_choose_draw);
  const canHit = Boolean(table?.can_hit);
  const canStand = Boolean(table?.can_stand);
  const isBlackjack = table?.game_type === "blackjack";
  const isBaccara = table?.game_type === "baccara";
  const isCardTable = isBlackjack || isBaccara;
  const showBaccaraOutcome = streets.showOutcome;
  const baccaraStreet = streets.street;
  const baccaraDealing = streets.dealing;
  const cardStreetAttr = isCardTable ? baccaraStreet : undefined;
  const lobbyHref = isBlackjack
    ? "/casino/play/blackjack?mode=players"
    : isBaccara
      ? "/casino/play/baccara?mode=players"
      : "/casino/play/pvp_dice?mode=players";
  const tableTitle = isBlackjack ? "Блэкджек" : isBaccara ? "Баккара" : "Кубики";

  async function withTable(
    action: (row: CasinoV2TableView) => Promise<{ table: CasinoV2TableView }>,
    fail: string,
  ) {
    if (!table || actionPending.current) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/tables/${table.table_id}`);
      return;
    }
    actionPending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await action(table);
      acceptTable(result.table);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : fail;
      setError(message);
      toast.error(message);
      try {
        acceptTable(await getCasinoV2Table(table.table_id));
      } catch {
        /* keep last */
      }
    } finally {
      actionPending.current = false;
      setBusy(false);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    }
  }

  async function onRoll() {
    if (!table) return;
    setRollingSeat(table.my_seat_no);
    const wait = prefersCasinoReducedMotion() ? 0 : 700;
    await withTable(
      (row) => rollCasinoV2Table(row.table_id, row.state_version),
      "Не удалось кинуть кубик",
    );
    window.setTimeout(() => setRollingSeat(null), wait);
  }

  async function onAddBot() {
    if (!table) return;
    await withTable((row) => addCasinoV2Bot(row.table_id, row.state_version), "Не удалось посадить бота");
  }

  const winners = new Set(table ? v2WinnerSeatNos(table) : []);
  const finished = table?.status === "finished";
  const myResult = table ? v2MyRoundResult(table) : null;
  const winnerSeats = (table?.roster ?? []).filter((seat) => winners.has(seat.seat_no) || seat.is_winner);
  const winnerLines = winnerSeats.map((seat) => {
    const name = seat.is_you ? "Вы" : seat.actor?.display_name || `Место ${seat.seat_no}`;
    const payout = v2SeatPayout(table!, seat.seat_no);
    return payout != null ? `${name} ${formatRub(payout)}` : name;
  });

  function goLobby() {
    const path = table ? v2LobbyPath(table.game_type) : lobbyHref;
    navigate(casinoTo(path));
  }
  const awaitingDraw = table?.game_state.phase === "draw_choice";
  const showDrawChoice = Boolean(awaitingDraw && showBaccaraOutcome);
  const showDrawActions = Boolean(canChooseDraw && showBaccaraOutcome);
  const showHitActions = Boolean((canHit || canStand) && showBaccaraOutcome && !finished);

  return (
    <div
      className="casino-v2-table"
      data-casino-v2-table={tableId || ""}
      data-casino-baccara-street={cardStreetAttr}
    >
      <TelegramMainButton
        text={
          finished && myResult
            ? "В лобби"
            : showDrawActions
            ? "Разделить банк"
            : canHit
              ? "Добрать"
              : canStand
                ? "Оставить"
                : canRoll
              ? remainSec != null
                ? `Кинуть кубик · ${remainSec} с`
                : "Кинуть кубик"
              : table?.can_start
                ? "Начать"
                : "Обновить"
        }
        visible={(Boolean(finished && myResult) || showDrawActions || showHitActions || canRoll || Boolean(table?.can_start)) && !busy}
        onClick={() => {
          if (finished && myResult) {
            goLobby();
          } else if (showDrawActions) {
            void withTable(
              (row) => chooseCasinoV2Draw(row.table_id, row.state_version, "tie_split"),
              "Не удалось разделить банк",
            );
          } else if (showHitActions && canHit) {
            void withTable((row) => hitCasinoV2Table(row.table_id, row.state_version), "Не удалось добрать");
          } else if (showHitActions && canStand) {
            void withTable((row) => standCasinoV2Table(row.table_id, row.state_version), "Не удалось оставить");
          } else if (canRoll) void onRoll();
          else if (table?.can_start) void withTable((row) => startCasinoV2Table(row.table_id, row.state_version), "Не удалось начать");
        }}
      />
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo(lobbyHref)}>Лобби</Link>
        <span className="casino-crumb-sep" aria-hidden>
          /
        </span>
        <span>Стол</span>
      </nav>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {table ? (
        <>
          <header className="casino-game-room-head">
            <span className="casino-game-room-icon" aria-hidden>
              {isBlackjack ? <Spade size={22} /> : isBaccara ? <CreditCard size={22} /> : <Dices size={22} />}
            </span>
            <div className="casino-game-room-copy">
              <h1>{tableTitle}</h1>
              <p>
                Стол {table.max_seats} · комиссия {formatRub(table.commission_rub)} ·{" "}
                {winnerSeats.length > 1 ? "после комиссии" : "победителю"} {formatRub(table.net_payout_rub)}
                {" · "}
                {v2StatusLabel(table)}
                {awaitingDraw && remainSec != null ? ` · ${remainSec} с` : ""}
              </p>
            </div>
            <div className="casino-game-room-chips">
              <span>Ставка {formatRub(table.stake_rub)}</span>
              <span>Банк {formatRub(table.pot_rub)}</span>
            </div>
          </header>
          {baccaraDealing ? (
            <p className="casino-muted" data-casino-baccara-dealing={baccaraStreet}>
              {baccaratDealingLabel(baccaraStreet)}
            </p>
          ) : null}
          {table.status === "tie_break_running" ? (
            <p className="casino-muted">Ничья — лидеры кидают ещё раз. Ставки остаются в банке.</p>
          ) : null}
          {table.game_state.phase === "hitting" && streets.showOutcome && canHit && !finished ? (
            <p className="casino-muted">Добрать или оставить. Таймаут — авто-оставить.</p>
          ) : null}
          {showDrawChoice ? (
            <p data-casino-v2-draw-choice="1">
              Ничья у лидеров. Разделить банк после комиссии или перераздать карты лидерам?
              {canChooseDraw ? "" : " Ждём выбор участника…"}
            </p>
          ) : null}
          {showBaccaraOutcome && finished && myResult ? (
            <CasinoRoundResult result={myResult}>
              <Link to={casinoTo(lobbyHref)} className="casino-btn" data-casino-v2-replay="">
                В лобби
              </Link>
            </CasinoRoundResult>
          ) : showBaccaraOutcome && finished && winnerLines.length ? (
            <p data-casino-v2-result="1">
              {winnerLines.length === 1 ? "Победитель" : "Победители"}: <strong>{winnerLines.join(" · ")}</strong>
            </p>
          ) : null}
          <div className={`casino-game-arena${finished && myResult ? (myResult.kind === "win" ? " is-win" : myResult.kind === "loss" ? " is-lose" : " is-draw") : ""}`}>
            <span className="casino-game-arena-glow" aria-hidden />
            <CasinoV2CompactPlay
              table={table}
              busy={busy}
              rollingSeat={rollingSeat}
              onAddBot={table.can_add_bot ? () => void onAddBot() : undefined}
            />
          </div>
          <p className="casino-hmac-note">
            {isBlackjack
              ? "Колода HMAC на сервере. Чужие карты закрыты до итога. Добор или оставить — у себя на столе или в личке с ботом. При ничьей можно разделить банк или перераздать карты лидерам. Таймаут — раздел."
              : isBaccara
                ? "Колода HMAC на сервере. Ближе к девяти, третья карта при 5 и меньше. При ничьей можно разделить банк или перераздать карты лидерам. Таймаут — раздел."
                : "Грань считает HMAC на сервере, не генератор браузера. Кубы только показывают исход. Равные ставки, победитель забирает банк после 5% комиссии."}
          </p>
          {table.game_state.commit ? (
            <p className="casino-mono casino-muted">commit {String(table.game_state.commit).slice(0, 16)}…</p>
          ) : null}
          {table.game_state.seed ? <p className="casino-mono casino-muted">сид {table.game_state.seed}</p> : null}
          {showDrawActions ? (
            <div className="casino-v2-draw-actions" data-casino-v2-draw-actions="">
              <button
                type="button"
                className="casino-btn"
                data-casino-v2-split=""
                disabled={busy}
                onClick={() =>
                  void withTable(
                    (row) => chooseCasinoV2Draw(row.table_id, row.state_version, "tie_split"),
                    "Не удалось разделить банк",
                  )
                }
              >
                Разделить банк
                {remainSec != null ? ` · ${remainSec} с` : ""}
              </button>
              <button
                type="button"
                className="casino-btn casino-btn-ghost"
                data-casino-v2-redeal=""
                disabled={busy}
                onClick={() =>
                  void withTable(
                    (row) => chooseCasinoV2Draw(row.table_id, row.state_version, "redeal"),
                    "Не удалось перераздать",
                  )
                }
              >
                Перераздача лидерам
              </button>
            </div>
          ) : null}
          {showHitActions ? (
            <div className="casino-v2-draw-actions" data-casino-v2-hit-actions="">
              {canHit ? (
                <button
                  type="button"
                  className="casino-btn"
                  data-casino-v2-hit=""
                  disabled={busy}
                  onClick={() => void withTable((row) => hitCasinoV2Table(row.table_id, row.state_version), "Не удалось добрать")}
                >
                  Добрать{remainSec != null ? ` · ${remainSec} с` : ""}
                </button>
              ) : null}
              {canStand ? (
                <button
                  type="button"
                  className="casino-btn casino-btn-ghost"
                  data-casino-v2-stand=""
                  disabled={busy}
                  onClick={() => void withTable((row) => standCasinoV2Table(row.table_id, row.state_version), "Не удалось оставить")}
                >
                  Оставить
                </button>
              ) : null}
            </div>
          ) : null}
          {canRoll ? (
            <button
              type="button"
              className="casino-btn"
              data-casino-v2-roll=""
              disabled={busy}
              onClick={() => void onRoll()}
            >
              Кинуть кубик{remainSec != null ? ` · ${remainSec} с` : ""}
            </button>
          ) : null}
          {table.can_start ? (
            <button
              type="button"
              className="casino-btn"
              data-casino-v2-start=""
              disabled={busy}
              onClick={() => void withTable((row) => startCasinoV2Table(row.table_id, row.state_version), "Не удалось начать")}
            >
              Начать игру
            </button>
          ) : null}
          {table.can_leave ? (
            <button
              type="button"
              className="casino-btn casino-btn-ghost"
              disabled={busy}
              onClick={() => void withTable((row) => leaveCasinoV2Table(row.table_id, row.state_version), "Не удалось выйти")}
            >
              Выйти
            </button>
          ) : null}
          {table.can_cancel ? (
            <button
              type="button"
              className="casino-btn casino-btn-ghost"
              disabled={busy}
              onClick={() => void withTable((row) => cancelCasinoV2Table(row.table_id, row.state_version), "Не удалось отменить")}
            >
              Отменить стол
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
