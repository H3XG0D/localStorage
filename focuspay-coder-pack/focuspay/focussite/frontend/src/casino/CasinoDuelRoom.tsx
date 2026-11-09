import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { getCasinoDuelRoom, joinCasinoDuel, rollCasinoDuel, cancelCasinoDuel, type CasinoDuelCard, type CasinoRevealStep } from "@/lib/public";
import { useSession } from "@/lib/session";
import { asDiePips, CasinoDie, prefersCasinoReducedMotion } from "./CasinoDice";
import { CasinoPlayingCard } from "./CasinoPlayingCard";
import { CASINO_CATALOG, CASINO_BALANCE_EVENT } from "./gameCatalog";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { CasinoPlayerChip } from "./CasinoPlayerChip";
import { TelegramMainButton } from "./TelegramMainButton";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function lastSeatPips(steps: CasinoRevealStep[], seat: string): number | null {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (steps[index].seat === seat) return asDiePips(steps[index].value);
  }
  return null;
}

function cardsForSeat(steps: CasinoRevealStep[], seat: string): string[] {
  return steps.filter((step) => step.seat === seat && step.card).map((step) => String(step.card));
}

function isCardGame(gameType: string | undefined): boolean {
  return gameType === "baccara" || gameType === "blackjack";
}

function stepsSignature(steps: CasinoRevealStep[]): string {
  return steps.map((step) => `${step.seat}:${step.index}:${step.value ?? ""}:${step.card ?? ""}`).join("|");
}

export function CasinoDuelRoom() {
  const { duelId } = useParams();
  const navigate = useNavigate();
  const { isAuthed } = useSession();
  const [room, setRoom] = useState<CasinoDuelCard | null>(null);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [rollingSeat, setRollingSeat] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!duelId) return;
    const id = duelId;
    let cancelled = false;
    async function load(resetReveal: boolean) {
      try {
        const payload = await getCasinoDuelRoom(id);
        if (cancelled) return;
        setRoom(payload);
        if (resetReveal) {
          setRevealed(0);
          setRollingSeat(null);
        }
        setError("");
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError && (err.status === 404 || err.status === 409) && id.startsWith("web-")) {
            navigate(casinoTo(`/casino/tables/${id}`), { replace: true });
            return;
          }
          setError(err instanceof Error ? err.message : "Дуэль не найдена");
        }
      }
    }
    void load(true);
    const poll = window.setInterval(() => void load(false), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [duelId, navigate]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(tick);
  }, []);

  const steps = room?.steps ?? [];
  const isDice = room?.game_type === "pvp_dice";
  const isCards = isCardGame(room?.game_type);
  const revealWait = isDice && !prefersCasinoReducedMotion() ? 1100 : isCards && !prefersCasinoReducedMotion() ? 650 : 900;
  const revealKey = stepsSignature(steps);
  const lastStepKey = revealed > 0 ? `${steps[revealed - 1]?.seat}:${steps[revealed - 1]?.index}` : "";

  useEffect(() => {
    if (!steps.length || revealed >= steps.length) return;
    const timer = window.setTimeout(() => setRevealed((count) => count + 1), revealWait);
    return () => window.clearTimeout(timer);
  }, [revealKey, revealed, revealWait, steps.length]);

  const visible = steps.slice(0, revealed);

  useEffect(() => {
    if (!isDice || revealed <= 0) return;
    const step = steps[revealed - 1];
    if (!step) return;
    setRollingSeat(step.seat);
    const wait = prefersCasinoReducedMotion() ? 0 : 700;
    const timer = window.setTimeout(() => setRollingSeat(null), wait);
    return () => window.clearTimeout(timer);
  }, [isDice, revealed, lastStepKey]);

  const last = visible[visible.length - 1];
  const game = CASINO_CATALOG.find((item) => item.id === room?.game_type);
  const canJoin = Boolean(room && !room.is_mine && !room.opponent_occupied);
  const creatorCards = cardsForSeat(visible, "creator");
  const opponentCards = cardsForSeat(visible, "opponent");
  const creatorPips = lastSeatPips(visible, "creator");
  const opponentPips = lastSeatPips(visible, "opponent");
  const bothDiceIn = Boolean(isDice && creatorPips != null && opponentPips != null);
  const refunded = Boolean(room && ["cancelled", "canceled", "timeout"].includes(String(room.status)));
  const waitingDice = Boolean(isDice && !refunded && room?.house_will_roll && !bothDiceIn);
  const finished = Boolean(
    room && ["finished", "outcome_committed", "released", "settled", "completed"].includes(room.status),
  );
  const revealComplete = revealed >= steps.length;
  const showOpponentOutcome = finished && revealComplete;
  const winnerLabel =
    last?.leader === "creator" ? room?.creator_label : last?.leader === "opponent" ? room?.opponent_label : null;

  async function onJoin() {
    if (!room) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/duels/${room.game_id}`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await joinCasinoDuel(room.game_id);
      setRoom(result.duel);
      navigate(casinoTo(`/casino/duels/${result.game_id}`), { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти в дуэль");
    } finally {
      setBusy(false);
    }
  }

  async function onRoll() {
    if (!room) return;
    setBusy(true);
    setError("");
    setRollingSeat(room.is_mine ? "creator" : "opponent");
    try {
      const result = await rollCasinoDuel(room.game_id);
      setRoom(result.duel);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось кинуть кубик");
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    if (!room) return;
    if (!isAuthed) {
      goCasinoLogin(navigate, `/casino/duels/${room.game_id}`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await cancelCasinoDuel(room.game_id);
      setRoom(result.duel);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      toast.success("Игра отменена, ставка вернулась");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось отменить";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  const deadlineMs = room?.roll_deadline_at ? Date.parse(room.roll_deadline_at) : NaN;
  const remainSec = Number.isFinite(deadlineMs) ? Math.max(0, Math.ceil((deadlineMs - now) / 1000)) : null;
  const canRoll = Boolean(isDice && room?.can_roll);

  return (
    <div className="casino-duel-room" data-casino-duel-room="1">
      <TelegramMainButton
        text={
          canRoll
            ? remainSec != null
              ? `Кинуть кубик · ${remainSec} с`
              : "Кинуть кубик"
            : isAuthed
              ? "Войти в дуэль"
              : "Войти"
        }
        visible={(canJoin || canRoll) && !busy}
        onClick={() => {
          if (canRoll) void onRoll();
          else void onJoin();
        }}
      />
      <nav className="casino-crumb" aria-label="Навигация">
        <Link to={casinoTo("/casino")}>Лобби</Link>
        {game?.name || room?.game_type ? (
          <>
            <span className="casino-crumb-sep" aria-hidden>
              /
            </span>
            <span>{game?.name ?? room?.game_type}</span>
          </>
        ) : null}
      </nav>
      {error ? <p className="casino-duel-error">{error}</p> : null}
      {room ? (
        <>
          <h1>{game?.name ?? room.game_type}</h1>
          <p className="casino-muted">
            Ставка {formatRub(room.bet_rub)} · банк {formatRub(room.bank_rub)} ·{" "}
            <strong>на руки {formatRub(room.net_payout_rub)}</strong>
          </p>
          <div className="casino-duel-seats casino-cub-stage">
            <Seat
              title={room.creator_label || "Игрок"}
              actor={room.creator}
              active={last?.seat === "creator"}
              leading={Boolean(bothDiceIn && last?.leader === "creator")}
              sum={last?.creator_sum ?? 0}
              die={isDice}
              cards={isCards}
              hand={creatorCards}
              backs={isCards && creatorCards.length === 0 ? 2 : 0}
              pips={creatorPips}
              rolling={rollingSeat === "creator"}
              seat="creator"
              zeroScore={isCards}
            />
            <Seat
              title={room.opponent_label || "место свободно"}
              actor={room.opponent}
              empty={!room.opponent_occupied}
              active={last?.seat === "opponent"}
              leading={Boolean(showOpponentOutcome && bothDiceIn && last?.leader === "opponent")}
              sum={showOpponentOutcome ? (last?.opponent_sum ?? 0) : 0}
              vacant={!room.opponent_occupied && visible.length === 0}
              die={isDice}
              cards={isCards}
              hand={showOpponentOutcome ? opponentCards : []}
              backs={isCards && room.opponent_occupied && (!showOpponentOutcome || opponentCards.length === 0) ? 2 : 0}
              pips={showOpponentOutcome ? opponentPips : null}
              rolling={rollingSeat === "opponent" && showOpponentOutcome}
              seat="opponent"
              zeroScore={isCards}
              hiddenOutcome={!showOpponentOutcome}
            />
          </div>
          <ol className="casino-reveal" data-reveal-count={revealed}>
            {visible.map((step, index) => {
              const isOpponent = step.seat === "opponent";
              const hideStep = isOpponent && !showOpponentOutcome;
              return (
                <li key={`${step.seat}-${step.index}-${index}`} data-reveal-step={index} className={step.seat === last?.seat ? "is-current" : ""}>
                  {step.seat === "creator" ? room.creator_label : room.opponent_label}: {hideStep ? "скрыто до конца раунда" : (step.card ?? (step.value == null ? "—" : step.value))}
                  {step.leader && !hideStep ? ` · лидер ${step.leader === "creator" ? room.creator_label : room.opponent_label}` : ""}
                </li>
              );
            })}
          </ol>
          {isCards ? (
            <p className="casino-muted">
              Карты сдаёт HMAC-колода. Свои видны вам, чужие — рубашкой до конца раунда. Картинки показывают раздачу, не меняют
              исход.
            </p>
          ) : null}
          {steps.length === 0 ? (
            <p className="casino-muted">
              {room.opponent_occupied
                ? isCards
                  ? "Карты откроются по одной после раунда."
                  : room.house_will_roll
                    ? remainSec != null
                      ? `Кинь кубик. Если не кинете за ${remainSec} с — FocusBet кинет за вас.`
                      : "Кинь кубик. Если не кинете за 30 с — FocusBet кинет за вас."
                    : "Разрешение пойдёт по одному броску, не разом."
                : "Ждём соперника. Если уйдёшь со страницы — вернёшься сюда из списка по стрелке."}
            </p>
          ) : revealed < steps.length ? (
            <p className="casino-muted">
              Сейчас {isCards ? "карта" : "бросает"} {steps[revealed]?.seat === "creator" ? room.creator_label : room.opponent_label}…
            </p>
          ) : refunded ? (
            <p data-casino-duel-result="refund">
              Дуэль отменена — ставки вернулись на балансы. Начни новую из списка дуэлей.
            </p>
          ) : waitingDice ? (
            <p className="casino-muted" data-casino-waiting-roll="1">
              {canRoll
                ? remainSec
                  ? `Кинь кубик. Если не кинете за ${remainSec} с — FocusBet кинет за вас.`
                  : "Кинь кубик. Время вышло — FocusBet кинет за того, кто не бросил."
                : remainSec
                  ? `Ждём бросок соперника. Если не кинет за ${remainSec} с — FocusBet кинет за него.`
                  : "Ждём бросок соперника. FocusBet сейчас кинет за того, кто не бросил."}
            </p>
          ) : finished && revealComplete ? (
            <p data-casino-duel-result="1">
              {winnerLabel ? (
                <>
                  Победитель: <strong>{winnerLabel}</strong>
                  {` · на руки ${formatRub(room.net_payout_rub)}`}
                </>
              ) : (
                "Ничья — ставки возвращаются."
              )}
            </p>
          ) : revealComplete && last?.leader ? (
            <p>
              Лидер: <strong>{last.leader === "creator" ? room.creator_label : room.opponent_label}</strong>
              {isCards ? ` · очки ${last.creator_sum} : ${last.opponent_sum}` : ""}
            </p>
          ) : !revealComplete ? (
            <p className="casino-muted">Раунд идёт. Результат соперника скрыт до конца раздачи.</p>
          ) : (
            <p className="casino-muted">{isCards ? "Ничья по очкам." : "Ничья по открытым броскам."}</p>
          )}
          {canRoll ? (
            <button
              type="button"
              className="casino-btn"
              data-casino-roll=""
              disabled={busy}
              onClick={() => void onRoll()}
            >
              Кинуть кубик{remainSec != null ? ` · ${remainSec} с` : ""}
            </button>
          ) : null}
          {room.is_mine && !room.opponent_occupied && !refunded && !finished ? (
            <button
              type="button"
              className="casino-btn casino-btn-ghost"
              data-casino-duel-cancel=""
              disabled={busy}
              onClick={() => void onCancel()}
            >
              Отменить игру
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Seat({
  title,
  actor,
  empty,
  vacant,
  active,
  leading,
  sum,
  die,
  cards,
  hand,
  backs,
  pips,
  rolling,
  seat,
  zeroScore,
  hiddenOutcome,
}: {
  title: string;
  actor?: CasinoDuelCard["creator"];
  empty?: boolean;
  vacant?: boolean;
  active: boolean;
  leading: boolean;
  sum: number;
  die?: boolean;
  cards?: boolean;
  hand?: string[];
  backs?: number;
  pips?: number | null;
  rolling?: boolean;
  seat?: "creator" | "opponent";
  zeroScore?: boolean;
  hiddenOutcome?: boolean;
}) {
  const skipDealMotion = prefersCasinoReducedMotion();
  const shown = hiddenOutcome ? [] : hand || [];
  return (
    <div
      className={`casino-seat${cards ? " is-cards" : ""}${active ? " is-active" : ""}${leading ? " is-leader" : ""}`}
      data-seat-leader={leading ? "1" : "0"}
    >
      <CasinoPlayerChip actor={actor ?? null} empty={empty} size={40} />
      <strong>{title}</strong>
      {die ? <CasinoDie value={vacant ? null : pips ?? null} rolling={!vacant && rolling} seat={seat} /> : null}
      {cards ? (
        <div className="casino-card-hand" data-casino-card-hand={seat}>
          {shown.map((code, index) => (
            <CasinoPlayingCard
              key={`${code}-${index}`}
              code={code}
              dealing={!skipDealMotion && active && index === shown.length - 1}
            />
          ))}
          {Array.from({ length: backs || 0 }, (_, index) => (
            <CasinoPlayingCard key={`back-${index}`} faceDown />
          ))}
        </div>
      ) : null}
      <span>{vacant ? "—" : hiddenOutcome && !vacant ? "скрыто" : zeroScore ? `очки ${sum}` : sum || "·"}</span>
    </div>
  );
}
