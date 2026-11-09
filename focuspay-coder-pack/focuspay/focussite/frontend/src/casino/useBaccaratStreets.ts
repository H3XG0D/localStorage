import { useEffect, useState } from "react";
import type { CasinoV2TableView } from "@/lib/public";
import {
  baccaratElapsedMs,
  baccaratHandsFromSeats,
  baccaratRevealedAfter,
  baccaratRoundKey,
  baccaratShownCount,
  baccaratStreetAttr,
  baccaratStreetSteps,
  baccaratVisibleCards,
  blackjackHolesOpen,
  blackjackRoundKey,
  blackjackStreetHands,
  blackjackVisibleCards,
  faceCardCodes,
  type BaccaratStreetStep,
} from "./baccaratStreets";
import { prefersCasinoReducedMotion } from "./CasinoDice";

function seatFaceCards(cards: string[] | undefined): string[] {
  return faceCardCodes(cards);
}

function seatDisplayCards(cards: string[] | undefined, keepBacks: boolean): string[] {
  if (!keepBacks) return seatFaceCards(cards);
  return (cards || []).map(String).filter(Boolean);
}

function streetSnapshot(
  steps: BaccaratStreetStep[],
  dealtAt: string | undefined,
  skipMotion: boolean,
): { revealed: number; resultReady: boolean; nextWaitMs: number } {
  if (skipMotion && steps.length) {
    return { revealed: steps.length, resultReady: true, nextWaitMs: 0 };
  }
  return baccaratRevealedAfter(steps, baccaratElapsedMs(dealtAt, Date.now()));
}

export function useBaccaratStreets(table: CasinoV2TableView | null | undefined) {
  const [revealed, setRevealed] = useState(0);
  const [resultReady, setResultReady] = useState(false);
  const [revealKey, setRevealKey] = useState("");
  const isBaccara = table?.game_type === "baccara";
  const isBlackjack = table?.game_type === "blackjack";
  const isCardStreets = isBaccara || isBlackjack;
  const skipMotion = prefersCasinoReducedMotion();
  const holesOpen = Boolean(table && isBlackjack && blackjackHolesOpen(table.status, table.game_state.phase));
  const streetRoster =
    table && isBlackjack && !holesOpen
      ? table.roster.map((seat) =>
          seat.is_you ? seat : { ...seat, cards: seat.cards?.length ? ["back", "back"] : [] },
        )
      : table?.roster;
  const fullHands =
    isCardStreets && streetRoster ? baccaratHandsFromSeats(streetRoster, { keepBacks: isBlackjack }) : {};
  const streetHands = isBlackjack ? blackjackStreetHands(fullHands) : fullHands;
  const steps: BaccaratStreetStep[] = isCardStreets ? baccaratStreetSteps(streetHands) : [];
  const stepsSig = steps.map((step) => `${step.seat}:${step.index}`).join("|");
  const dealtAt = table?.game_state.cards_dealt_at;
  const roundKey =
    table && isBaccara
      ? baccaratRoundKey(table.table_id, table.game_state.commit, fullHands, dealtAt)
      : table && isBlackjack
        ? blackjackRoundKey(table.table_id, table.game_state.commit, fullHands, dealtAt)
        : "";
  const stepCount = steps.length;

  if (revealKey !== roundKey) {
    setRevealKey(roundKey);
    const snap = streetSnapshot(steps, dealtAt, skipMotion);
    setRevealed(snap.revealed);
    setResultReady(snap.resultReady);
  }

  useEffect(() => {
    if (!isCardStreets || !stepCount) return;
    const apply = (snap: { revealed: number; resultReady: boolean; nextWaitMs: number }) => {
      setRevealed(snap.revealed);
      setResultReady(snap.resultReady);
      return snap;
    };
    if (skipMotion) {
      apply({ revealed: stepCount, resultReady: true, nextWaitMs: 0 });
      return;
    }
    let timer = 0;
    const tick = () => {
      const snap = apply(streetSnapshot(steps, dealtAt, false));
      if (!snap.resultReady) {
        timer = window.setTimeout(tick, Math.max(16, snap.nextWaitMs));
      }
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [isCardStreets, skipMotion, roundKey, stepsSig, dealtAt, stepCount]);

  const streetRevealed = revealKey === roundKey ? revealed : streetSnapshot(steps, dealtAt, skipMotion).revealed;
  const streetResultReady =
    revealKey === roundKey ? resultReady : streetSnapshot(steps, dealtAt, skipMotion).resultReady;
  const street = isCardStreets ? baccaratStreetAttr(steps, streetRevealed, streetResultReady) : "";
  const dealing = Boolean(isCardStreets && stepCount && !streetResultReady);
  const showOutcome = !isCardStreets || !stepCount || streetResultReady;

  function visibleForSeat(seatNo: number, rawCards: string[] | undefined): string[] {
    const full = seatDisplayCards(rawCards, isBlackjack);
    if (!isCardStreets) return full;
    const shown = baccaratShownCount(steps, streetRevealed, seatNo);
    if (isBlackjack) return blackjackVisibleCards(full, shown, streetResultReady);
    return baccaratVisibleCards(full, shown);
  }

  function dealingSeat(seatNo: number): boolean {
    const last = streetRevealed > 0 ? steps[streetRevealed - 1] : null;
    return Boolean(isCardStreets && last && last.seat === seatNo && !skipMotion && !streetResultReady);
  }

  return {
    isBaccara,
    isBlackjack,
    isCardStreets,
    skipMotion,
    steps,
    street,
    dealing,
    showOutcome,
    streetRevealed,
    visibleForSeat,
    dealingSeat,
    faceCards: seatFaceCards,
  };
}
