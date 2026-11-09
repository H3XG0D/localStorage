import type { CasinoV2TableView } from "@/lib/public";

export type V2RoundKind = "win" | "loss" | "tie" | "refund";

export type V2MyRoundResult = {
  kind: V2RoundKind;
  title: string;
  amountRub: number;
  signedLabel: string;
  detail: string;
};

export function formatCasinoRub(value: string | number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ₽`;
}

export function v2LobbyPath(gameType: string): string {
  if (gameType === "blackjack") return "/casino/play/blackjack?mode=players";
  if (gameType === "baccara") return "/casino/play/baccara?mode=players";
  return "/casino/play/pvp_dice?mode=players";
}

export function v2StatusLabel(table: CasinoV2TableView): string {
  if (table.status === "finished") return "готово";
  if (table.status === "cancelled") return "отмена";
  if (table.countdown_ends_at && (table.status === "open" || table.status === "ready")) return "игра начинается";
  if (table.game_state.phase === "draw_choice") return "ничья — выбор";
  if (table.game_state.phase === "hitting") return "добор";
  if (table.status === "open" || table.status === "ready") return "ждёт игроков";
  if (table.status === "running") return "идёт игра";
  if (table.status === "tie_break_running") return "переброс";
  return table.status;
}

export function v2SeatPayout(table: CasinoV2TableView, seatNo: number): string | null {
  const fromSeat = table.roster.find((row) => row.seat_no === seatNo)?.payout_rub;
  if (fromSeat != null && String(fromSeat) !== "") return String(fromSeat);
  const fromSettlement = table.settlement?.payouts?.find((row) => row.seat_no === seatNo)?.amount_rub;
  return fromSettlement != null ? String(fromSettlement) : null;
}

export function v2WinnerSeatNos(table: CasinoV2TableView): number[] {
  if (table.settlement?.winner_seat_nos?.length) return table.settlement.winner_seat_nos;
  if (table.outcome?.winner_seat_nos?.length) return table.outcome.winner_seat_nos;
  return table.roster.filter((seat) => seat.is_winner).map((seat) => seat.seat_no);
}

export function v2ReplayBody(table: CasinoV2TableView) {
  const maxSeats = Math.max(2, Math.min(6, Number(table.max_seats) || 2));
  return {
    game_type: table.game_type,
    stake_rub: Number(table.stake_rub) || 50,
    max_seats: maxSeats,
    bot_count: 0,
    autojoin: false,
  };
}

export function v2NoticeKey(table: CasinoV2TableView): string {
  return `v2-result:${table.table_id}:${table.state_version}`;
}

export function v2MyRoundResult(table: CasinoV2TableView): V2MyRoundResult | null {
  if (table.status !== "finished" || !table.is_seated) return null;
  const stake = Number(table.stake_rub) || 0;
  const mySeat =
    table.roster.find((seat) => seat.is_you) ||
    table.roster.find((seat) => seat.seat_no === table.my_seat_no);
  if (!mySeat) return null;
  const winners = v2WinnerSeatNos(table);
  const kindRaw = String(table.settlement?.outcome_kind || table.outcome?.kind || "");
  const payout = Number(v2SeatPayout(table, mySeat.seat_no) || 0);
  const iWon = Boolean(mySeat.is_winner || winners.includes(mySeat.seat_no));
  const split = kindRaw === "tie" || kindRaw === "tie_split" || (iWon && winners.length > 1);

  if (kindRaw === "refund" || kindRaw === "draw") {
    return {
      kind: "refund",
      title: "Ничья",
      amountRub: stake,
      signedLabel: `+${formatCasinoRub(stake)}`,
      detail: "Ставка вернулась на баланс",
    };
  }

  if (split && iWon) {
    return {
      kind: "tie",
      title: "Ничья",
      amountRub: payout,
      signedLabel: `+${formatCasinoRub(payout)}`,
      detail: `Банк после комиссии разделили · ставка ${formatCasinoRub(stake)}`,
    };
  }

  if (iWon) {
    const profit = Math.round((payout - stake) * 100) / 100;
    return {
      kind: "win",
      title: "Победа",
      amountRub: payout,
      signedLabel: `+${formatCasinoRub(payout)}`,
      detail: `Ставка ${formatCasinoRub(stake)} · прибыль ${formatCasinoRub(profit)}`,
    };
  }

  return {
    kind: "loss",
    title: "Проигрыш",
    amountRub: stake,
    signedLabel: `−${formatCasinoRub(stake)}`,
    detail: winners.length
      ? `Банк ${formatCasinoRub(table.net_payout_rub)} ушёл победителю`
      : `Ставка ${formatCasinoRub(stake)} сгорела`,
  };
}
