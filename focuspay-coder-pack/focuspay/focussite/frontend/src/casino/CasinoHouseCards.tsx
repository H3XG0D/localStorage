import { useEffect, useRef, useState } from "react";
import type { CasinoPlayResult } from "@/lib/public";
import { prefersCasinoReducedMotion } from "./CasinoDice";
import { CasinoPlayingCard } from "./CasinoPlayingCard";
import {
  HOUSE_CARD_DEAL_MS,
  HOUSE_CARD_RESULT_BEAT_MS,
  cardsFromPlayResult,
} from "./houseCards";

function handCards(
  codes: string[],
  shown: number,
  opts: { skipMotion: boolean; dealing: boolean; prefix: string },
) {
  const face = codes.slice(0, shown);
  const hidden = codes.slice(shown);
  return (
    <>
      {face.map((code, index) => (
        <CasinoPlayingCard
          key={`${code}-${index}`}
          code={code}
          dealing={opts.dealing && !opts.skipMotion && index === shown - 1}
        />
      ))}
      {hidden.map((_, index) => (
        <CasinoPlayingCard key={`${opts.prefix}-back-${shown + index}`} faceDown />
      ))}
    </>
  );
}

export function CasinoHouseCards({
  gameType,
  last,
  rolling,
  acting = false,
  onHit,
  onStand,
  onRevealReady,
}: {
  gameType: "baccara" | "blackjack";
  last: CasinoPlayResult | null;
  rolling: boolean;
  acting?: boolean;
  onHit?: () => void;
  onStand?: () => void;
  onRevealReady?: () => void;
}) {
  const live = gameType === "blackjack" && last?.phase === "player_turn";
  const playerCards = cardsFromPlayResult(last, "player");
  const houseCards = cardsFromPlayResult(last, "house");
  const holeCount = live ? Math.max(1, Number(last?.house_hidden) || 1) : 0;
  const skipMotion = prefersCasinoReducedMotion();
  const [shownPlayer, setShownPlayer] = useState(0);
  const [shownHouse, setShownHouse] = useState(0);
  const [resultReady, setResultReady] = useState(false);
  const playerKey = playerCards.join(",");
  const houseKey = `${houseCards.join(",")}|${holeCount}`;
  const roundKey = `${last?.game_id || ""}|${playerKey}|${houseKey}`;
  const onRevealReadyRef = useRef(onRevealReady);
  onRevealReadyRef.current = onRevealReady;

  useEffect(() => {
    if (rolling) {
      setShownPlayer(0);
      setShownHouse(0);
      setResultReady(false);
    }
  }, [rolling]);

  useEffect(() => {
    setShownPlayer((prev) => (prev > playerCards.length ? 0 : prev));
  }, [playerKey, playerCards.length]);

  useEffect(() => {
    if (live) {
      setShownHouse(houseCards.length);
      return;
    }
    setShownHouse((prev) => (prev > houseCards.length ? 0 : prev));
  }, [houseKey, houseCards.length, live]);

  useEffect(() => {
    if (rolling || !playerCards.length) return;
    if (shownPlayer >= playerCards.length) return;
    const wait = skipMotion ? 0 : HOUSE_CARD_DEAL_MS;
    const timer = window.setTimeout(() => setShownPlayer((count) => count + 1), wait);
    return () => window.clearTimeout(timer);
  }, [rolling, playerCards.length, shownPlayer, skipMotion, playerKey]);

  useEffect(() => {
    if (live || rolling || shownPlayer < playerCards.length || !houseCards.length) return;
    if (shownHouse >= houseCards.length) return;
    const wait = skipMotion ? 0 : HOUSE_CARD_DEAL_MS;
    const timer = window.setTimeout(() => setShownHouse((count) => count + 1), wait);
    return () => window.clearTimeout(timer);
  }, [rolling, shownPlayer, playerCards.length, houseCards.length, shownHouse, skipMotion, houseKey, live]);

  const kind = last?.outcome?.kind;
  const won = kind === "win";
  const tie = kind === "tie";
  const pending = live || kind === "pending";
  const playerScore = last?.player_score ?? last?.rng?.player_score;
  const houseScore = last?.house_score ?? last?.rng?.house_score;
  const handsReady = Boolean(
    last && !rolling && shownPlayer >= playerCards.length && (live || shownHouse >= houseCards.length),
  );

  useEffect(() => {
    if (!handsReady || pending) {
      setResultReady(false);
      return;
    }
    if (skipMotion) {
      setResultReady(true);
      return;
    }
    const timer = window.setTimeout(() => setResultReady(true), HOUSE_CARD_RESULT_BEAT_MS);
    return () => window.clearTimeout(timer);
  }, [handsReady, pending, skipMotion, roundKey]);

  const done = resultReady && !pending;
  const canHit = Boolean(live && handsReady && !acting && last?.actions?.includes("hit"));
  const canStand = Boolean(live && handsReady && !acting && last?.actions?.includes("stand"));
  const formatRub = (value: string | number | undefined) =>
    `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ₽`;
  const revealPhase = rolling || (last && !handsReady) ? "dealing" : done ? "outcome" : handsReady ? "ready" : "idle";

  useEffect(() => {
    if (rolling) return;
    if (live && handsReady) onRevealReadyRef.current?.();
    else if (resultReady) onRevealReadyRef.current?.();
  }, [rolling, live, handsReady, resultReady, roundKey]);

  return (
    <div
      className={`casino-cub-stage casino-house-cards${done ? (won ? " is-win" : tie ? "" : " is-lose") : ""}`}
      data-casino-house-cards={gameType}
      data-casino-house-reveal={revealPhase}
      data-casino-house-outcome={done ? (won ? "win" : tie ? "tie" : "loss") : pending ? "pending" : "hidden"}
      data-casino-bj-phase={live ? "player_turn" : done ? "finished" : ""}
    >
      <div className="casino-duel-seats">
        <div className="casino-seat is-cards" data-casino-house-seat="player">
          <strong>Вы</strong>
          <div className="casino-card-hand" data-casino-card-hand="player">
            {rolling
              ? [0, 1].map((index) => <CasinoPlayingCard key={`p-back-${index}`} faceDown />)
              : handCards(playerCards, shownPlayer, {
                  skipMotion,
                  dealing: true,
                  prefix: "p",
                })}
          </div>
          <span>{handsReady ? `очки ${playerScore ?? "—"}` : rolling || last ? "…" : "—"}</span>
        </div>
        <span className="casino-dice-vs" aria-hidden>
          vs
        </span>
        <div className="casino-seat is-cards" data-casino-house-seat="house">
          <strong>FocusBet</strong>
          <div className="casino-card-hand" data-casino-card-hand="house">
            {rolling ? (
              [0, 1].map((index) => <CasinoPlayingCard key={`h-back-${index}`} faceDown />)
            ) : (
              <>
                {handCards(houseCards, live ? houseCards.length : shownHouse, {
                  skipMotion,
                  dealing: !live,
                  prefix: "h",
                })}
                {live
                  ? Array.from({ length: holeCount }, (_, index) => (
                      <CasinoPlayingCard key={`hole-${index}`} faceDown />
                    ))
                  : null}
              </>
            )}
          </div>
          <span>
            {live && handsReady
              ? `открытая ${houseScore ?? "—"}`
              : handsReady
                ? `очки ${houseScore ?? "—"}`
                : rolling || last
                  ? "…"
                  : "—"}
          </span>
        </div>
      </div>
      {live ? (
        <div className="casino-bj-actions">
          <button
            type="button"
            className="casino-btn"
            data-casino-bj-hit=""
            disabled={!canHit}
            onClick={() => onHit?.()}
          >
            Добрать
          </button>
          <button
            type="button"
            className="casino-btn casino-btn-ghost"
            data-casino-bj-stand=""
            disabled={!canStand}
            onClick={() => onStand?.()}
          >
            Оставить
          </button>
        </div>
      ) : null}
      {done ? (
        <div className={`casino-round-result${won ? " is-win" : tie ? "" : " is-lose"}`}>
          <strong>{won ? "Победа" : tie ? "Ничья" : "Поражение"}</strong>
          <p>
            Вы {playerScore ?? "—"} · FocusBet {houseScore ?? "—"} · ставка {formatRub(last?.stake_rub)} · выплата{" "}
            {formatRub(last?.payout_rub)}
          </p>
          {last?.rng?.commit ? <p className="casino-mono">commit {String(last.rng.commit).slice(0, 16)}…</p> : null}
        </div>
      ) : (
        <p className="casino-muted">
          {rolling || (last && !handsReady)
            ? "Раздача HMAC-колоды…"
            : live
              ? "Добрать карту или оставить. У FocusBet одна карта скрыта, пока вы не остановитесь."
              : "Поставьте сумму слева. Сверху карты FocusBet, снизу ваши. Исход считает сервер, картинки его не меняют."}
        </p>
      )}
      <p className="casino-hmac-note">
        {gameType === "blackjack"
          ? "Вы выбираете добор. Дилер открывает дырку и сам добирает до 17. Карты с committed HMAC-колоды. Выплата — после комиссии с выигрыша."
          : "Карты с committed HMAC-колоды. Каждый 1×1 считается с домом отдельно, без общего банка. Выплата — после комиссии с выигрыша."}
      </p>
    </div>
  );
}
