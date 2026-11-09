import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Swords } from "lucide-react";
import type { CasinoV2TableView } from "@/lib/public";
import { asDiePips, CasinoDie } from "./CasinoDice";
import { CasinoPlayerChip } from "./CasinoPlayerChip";
import { CasinoPlayingCard } from "./CasinoPlayingCard";
import { baccaratHandScore, blackjackHandScore, blackjackHolesOpen, faceCardCodes } from "./baccaratStreets";
import { useBaccaratStreets } from "./useBaccaratStreets";
import { CasinoStartCountdown } from "./CasinoStartCountdown";
import { formatCasinoRub, v2MyRoundResult, v2SeatPayout, v2StatusLabel, v2WinnerSeatNos } from "./v2RoundResult";

function seatFaceCards(cards: string[] | undefined): string[] {
  return faceCardCodes(cards);
}

export { v2StatusLabel };

function seatCopy(input: {
  empty: boolean;
  rolling: boolean;
  isBaccara: boolean;
  isBlackjack: boolean;
  cards: string[];
  cardFaces: string[];
  showOutcome: boolean;
  score: number | null | undefined;
  total: number | null | undefined;
  won: boolean;
  lost: boolean;
  leading: boolean;
  payout: number | string | null;
}): { value: string; hint: string } {
  if (input.empty) return { value: "—", hint: "Свободно" };
  if (input.isBaccara) {
    const faces = faceCardCodes(input.cards);
    if (!faces.length) return { value: "—", hint: input.cards.length ? "Закрыто" : "Ожидание раздачи" };
    const hint = faces.length === 3
      ? "Третья карта"
      : input.showOutcome
        ? "Итог руки"
        : "Очки открытых карт";
    return { value: String(baccaratHandScore(faces)), hint };
  }
  if (input.isBlackjack) {
    if (!input.cardFaces.length) return { value: "—", hint: "Ожидание раздачи" };
    const bust = input.cards.length >= 2 && input.showOutcome && input.score != null && input.score > 21;
    return {
      value: bust ? "Перебор" : String(blackjackHandScore(input.cardFaces)),
      hint: bust ? `${input.score} очков` : input.showOutcome ? "Итог руки" : "Очки открытых карт",
    };
  }
  if (input.rolling) return { value: "—", hint: "Бросок…" };
  if (input.total == null) return { value: "—", hint: "Ожидание" };
  const extra = input.won && input.payout != null ? ` · +${formatCasinoRub(input.payout)}` : "";
  return {
    value: String(input.total),
    hint: `${input.won ? "Победа" : input.lost ? "Проигрыш" : input.leading ? "Лидер" : "Результат"}${extra}`,
  };
}

export function CasinoV2CompactPlay({
  table,
  busy,
  facesOnly = false,
  rollingSeat = null,
  onAddBot,
}: {
  table: CasinoV2TableView;
  busy?: boolean;
  facesOnly?: boolean;
  rollingSeat?: number | null;
  onAddBot?: () => void;
}) {
  const isBlackjack = table.game_type === "blackjack";
  const isBaccara = table.game_type === "baccara";
  const isCardTable = isBlackjack || isBaccara;
  const streets = useBaccaratStreets(table);
  const winners = new Set(v2WinnerSeatNos(table));
  const finished = table.status === "finished";
  const showOutcome = streets.showOutcome || finished;
  const holesOpen = blackjackHolesOpen(table.status, table.game_state.phase);
  const [session, setSession] = useState({ wins: 0, losses: 0, draws: 0 });
  const seenRound = useRef("");
  useEffect(() => {
    if (isCardTable || table.status !== "finished" || !table.is_seated) return;
    const key = `${table.table_id}:${table.state_version}`;
    if (seenRound.current === key) return;
    seenRound.current = key;
    const mine = v2MyRoundResult(table);
    if (!mine) return;
    setSession((current) => {
      if (mine.kind === "win") return { ...current, wins: current.wins + 1 };
      if (mine.kind === "loss") return { ...current, losses: current.losses + 1 };
      return { ...current, draws: current.draws + 1 };
    });
  }, [isCardTable, table]);
  const sessionTotal = session.wins + session.losses + session.draws;
  const statusNote = isBaccara
    ? "Ближе к девяти"
    : isBlackjack
      ? "Ближе к 21 без перебора"
      : "Большее число забирает раунд";
  return (
    <>
    <div className="casino-game-arena-bar">
      <span className="casino-game-vs"><Swords size={15} aria-hidden />VS</span>
      <div className="casino-game-status">
        <strong>{v2StatusLabel(table)}</strong>
        <span>{statusNote}</span>
      </div>
      {!isCardTable ? <CasinoStartCountdown endsAt={table.countdown_ends_at} ring label="Старт" /> : null}
    </div>
    <div
      className={`casino-v2-seats casino-cub-stage${facesOnly ? " is-faces" : ""}${isCardTable ? " is-cards" : ""}`}
      data-casino-v2-seats={table.max_seats}
      data-casino-baccara-street={isCardTable ? streets.street || undefined : undefined}
    >
      {Array.from({ length: table.max_seats }, (_, index) => {
        const seatNo = index + 1;
        const seat = table.roster.find((row) => row.seat_no === seatNo);
        const empty = !seat;
        const won = Boolean(showOutcome && finished && seat && (seat.is_winner || winners.has(seatNo)));
        const decided = Boolean(showOutcome && finished && (winners.size > 0 || table.roster.some((row) => row.is_winner)));
        const lost = Boolean(decided && seat && !won);
        const leading = Boolean(
          showOutcome && !finished && seat && (seat.is_leader || (table.game_state.phase === "draw_choice" && winners.has(seatNo))),
        );
        const canAdd = Boolean(empty && table.can_add_bot && onAddBot && !busy);
        const dealt = isCardTable ? streets.visibleForSeat(seatNo, seat?.cards) : seatFaceCards(seat?.cards);
        const conceal = isBlackjack && !holesOpen && Boolean(seat) && !seat?.is_you;
        const cards = conceal ? ["back", "back"] : dealt;
        const cardFaces = faceCardCodes(cards);
        const hand = !isCardTable ? [] : cards.length ? cards : empty ? [] : ["back", "back"];
        const dealingCard = streets.dealingSeat(seatNo);
        const payout = seat ? v2SeatPayout(table, seatNo) : null;
        const bot = seat?.participant_kind === "bot";
        const name = empty ? "Пусто" : seat?.is_you ? "Вы" : seat?.actor?.display_name || `Место ${seatNo}`;
        const tag = empty ? "Место" : seat?.is_you ? "Вы" : bot ? "Бот" : "Игрок";
        const who = empty ? "Свободное место" : seat?.is_you ? "Ваше место" : bot ? "Бот за столом" : "За столом";
        const copy = seatCopy({
          empty,
          rolling: !empty && rollingSeat === seatNo,
          isBaccara,
          isBlackjack,
          cards,
          cardFaces,
          showOutcome,
          score: seat?.score,
          total: seat?.total,
          won,
          lost,
          leading,
          payout,
        });
        const tone = won ? " is-winner" : lost ? " is-loser" : leading ? " is-leader" : "";
        const rolling = !empty && rollingSeat === seatNo;
        const stage = isCardTable ? (
          <div className="casino-v2-hand" data-casino-v2-hand={seatNo} style={{ "--cards": Math.max(hand.length, 1) } as CSSProperties}>
            {hand.map((code, cardIndex) => (
              <CasinoPlayingCard
                key={`${seatNo}-${cardIndex}-${code}`}
                code={code}
                dealing={dealingCard && cardIndex === cards.length - 1}
              />
            ))}
          </div>
        ) : (
          <CasinoDie
            value={empty ? null : asDiePips(seat?.pips)}
            rolling={rolling}
            seat={`seat${seatNo}`}
          />
        );
        const body = (
          <>
            <header className="casino-game-seat-head">
              <CasinoPlayerChip actor={seat?.actor ?? null} empty={empty} size={40} linked={!bot} />
              <div className="casino-game-seat-who">
                <strong>{name}</strong>
                <span>{who}</span>
              </div>
              <span className="casino-game-seat-tag">{tag}</span>
            </header>
            <div className="casino-game-seat-stage">{stage}</div>
            <footer className="casino-game-seat-foot">
              <span className="casino-seat-result casino-game-seat-value">{copy.value}</span>
              <span className="casino-game-seat-hint">{canAdd ? "Посадить бота" : copy.hint}</span>
            </footer>
          </>
        );
        if (canAdd) {
          return (
            <button
              key={seatNo}
              type="button"
              className={`casino-seat casino-game-seat is-empty${tone}`}
              data-v2-seat={seatNo}
              data-v2-result=""
              data-casino-v2-add-bot=""
              disabled={busy}
              onClick={onAddBot}
            >
              {body}
            </button>
          );
        }
        return (
          <article
            key={seatNo}
            className={`casino-seat casino-game-seat${tone}${empty ? " is-empty" : ""}${rolling ? " is-rolling" : ""}`}
            data-v2-seat={seatNo}
            data-v2-result={won ? "win" : lost ? "lose" : ""}
          >
            {body}
          </article>
        );
      })}
    </div>
    {!isCardTable && sessionTotal > 0 ? (
      <p className="casino-dice-score" data-casino-dice-score="">
        Сессия: {session.wins} побед · {session.losses} поражений · {session.draws} ничьих
      </p>
    ) : null}
    {isBaccara ? (
      <details className="casino-table-rules">
        <summary>Правила игры</summary>
        <p>Туз = 1 · 2–9 = номинал · 10, J, Q, K = 0. Сумма по модулю 10. При результате двух карт 5 и меньше руке добавляется одна третья карта. Побеждает единственная наибольшая сумма. Если максимум совпадает у нескольких участников, ставки возвращаются всем.</p>
        <p>Ставка списывается при входе. Пустое место можно закрыть ботом.</p>
      </details>
    ) : null}
    {isBlackjack ? (
      <details className="casino-table-rules">
        <summary>Правила игры</summary>
        <p>Туз = 1 или 11 · 2–9 = номинал · 10, J, Q, K = 10. Перебор больше 21 проигрывает. Добор и «оставить» — ваш ход. Побеждает единственная наибольшая сумма без перебора. При равенстве максимума — ничья, ставки возвращаются.</p>
        <p>Ставка списывается при входе. Пустое место можно закрыть ботом.</p>
      </details>
    ) : null}
    </>
  );
}
