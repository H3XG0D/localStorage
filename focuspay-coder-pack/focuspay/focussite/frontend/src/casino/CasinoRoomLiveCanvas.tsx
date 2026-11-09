import { Plus } from "lucide-react";
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CasinoRoomPlayer, CasinoRoomSnapshot } from "@/lib/public";
import { CasinoPlayerAvatar, CasinoPlayerChip } from "./CasinoPlayerChip";
import { CASINO_BALANCE_EVENT, CASINO_BALANCE_HOLD_EVENT } from "./gameCatalog";
import { WEIGHTED_REEL_SPIN_MS, WEIGHTED_REEL_WINNER_INDEX, buildWeightedReel } from "./weightedReel";

const SLOT_DESKTOP_PX = 72;
const SLOT_MOBILE_PX = 56;
const WINNER_INDEX = WEIGHTED_REEL_WINNER_INDEX;
const SPIN_MS = WEIGHTED_REEL_SPIN_MS;

function slotPx(): number {
  try {
    if (window.matchMedia("(max-width: 767px)").matches) return SLOT_MOBILE_PX;
  } catch {
    /* SSR */
  }
  return SLOT_DESKTOP_PX;
}

function reduceMotion(): boolean {
  try {
    if (document.documentElement.classList.contains("casino-reduce-motion")) return true;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function CasinoRoomLiveCanvas({
  room,
  busy,
  compact,
  layout = "ring",
  forceReel,
  onAddBot,
  onJoin,
}: {
  room: CasinoRoomSnapshot;
  busy?: boolean;
  compact?: boolean;
  layout?: "ring" | "row";
  forceReel?: boolean;
  onAddBot?: () => void;
  onJoin?: () => void;
}) {
  const [spinning, setSpinning] = useState(false);
  const [shift, setShift] = useState(0);
  const [spinEase, setSpinEase] = useState(false);
  const spinningRef = useRef(false);
  const spunKeyRef = useRef<string | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const spinTimer = useRef(0);
  const pendingKick = useRef(false);

  const startSpin = useCallback((snap: CasinoRoomSnapshot, winnerId: number) => {
    if (spinningRef.current) return;
    const key = `${snap.room_id}:${winnerId}:${snap.winner_index ?? ""}`;
    if (spunKeyRef.current === key) return;
    spunKeyRef.current = key;
    spinningRef.current = true;
    pendingKick.current = true;
    setSpinning(true);
    window.dispatchEvent(new Event(CASINO_BALANCE_HOLD_EVENT));
  }, []);

  useLayoutEffect(() => {
    if (!spinning || !pendingKick.current) return;
    pendingKick.current = false;
    const slot = layout === "row" ? 44 : compact ? Math.min(slotPx(), 48) : slotPx();
    const viewport =
      viewportRef.current?.clientWidth ||
      viewportRef.current?.parentElement?.clientWidth ||
      Math.min(window.innerWidth - 24, layout === "row" ? 360 : compact ? 280 : 640);
    const target = WINNER_INDEX * slot + slot / 2 - viewport / 2;
    if (reduceMotion()) {
      setSpinEase(false);
      setShift(target);
      window.setTimeout(() => {
        spinningRef.current = false;
        setSpinning(false);
        window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
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
    }, SPIN_MS + 200);
    return () => window.clearTimeout(spinTimer.current);
  }, [compact, layout, spinning]);

  useLayoutEffect(() => {
    if ((room.status === "locked" || room.status === "settled") && room.winner_id != null) {
      startSpin(room, room.winner_id);
    }
  }, [room, startSpin]);

  const players = room.players ?? [];
  const winnerId = room.winner_id ?? null;
  const reel = useMemo(() => {
    if (!spinning) return [];
    return buildWeightedReel(players, (row) => row.amount_rub || room.stake_rub || 1, winnerId);
  }, [players, room.stake_rub, spinning, winnerId]);
  const canAddBot = Boolean(onAddBot && room.my_seat != null && room.can_add_bot);
  const joinable = Boolean(onJoin && room.status === "open" && room.my_seat == null && room.filled < room.seat_count);
  const bySeat = new Map(players.map((player) => [player.seat_no, player]));
  const showReel = spinning || Boolean(forceReel && layout === "row");
  const avatarSize = layout === "row" ? 48 : compact ? 36 : 48;

  return (
    <div className={`casino-room-live${layout === "row" ? " is-row" : ""}`} data-casino-room-live={room.room_id}>
      <div
        className={`casino-jackpot-reel is-drama${showReel ? " is-live" : " is-idle"}`}
        ref={viewportRef}
        data-casino-jackpot-reel={spinning ? "spin" : "wait"}
        aria-hidden={!spinning}
      >
        {spinning ? (
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
                  <CasinoPlayerAvatar actor={player} size={avatarSize} className="casino-jackpot-avatar-img" />
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
      {layout === "row" ? (
        <div className="casino-room-row-avatars">
          {Array.from({ length: Math.max(2, room.seat_count) }, (_, index) => {
            const player = bySeat.get(index);
            if (player) {
              return (
                <CasinoPlayerChip
                  key={`${player.user_id}-${player.seat_no}`}
                  actor={player}
                  size={avatarSize}
                  linked={(player.participant_kind || "player") !== "bot" && player.user_id !== 0}
                />
              );
            }
            if (joinable) {
              return (
                <button key={index} type="button" className="casino-room-join" disabled={busy} aria-label="Сесть" onClick={onJoin}>
                  <Plus size={22} strokeWidth={3} />
                </button>
              );
            }
            if (canAddBot) {
              return (
                <button
                  key={index}
                  type="button"
                  className="casino-room-join"
                  data-casino-room-add-bot=""
                  disabled={busy}
                  aria-label="Добавить бота"
                  onClick={onAddBot}
                >
                  <Plus size={22} strokeWidth={3} />
                </button>
              );
            }
            return <span key={index} className="casino-room-slot is-empty" />;
          })}
        </div>
      ) : spinning ? null : (
        <div className="casino-felt-ring" aria-hidden={false}>
          {Array.from({ length: room.seat_count }, (_, index) => {
            const player = bySeat.get(index);
            const empty = !player;
            if (empty && canAddBot) {
              return (
                <button
                  key={index}
                  type="button"
                  className="casino-felt-seat is-empty"
                  data-casino-room-add-bot=""
                  disabled={busy}
                  onClick={onAddBot}
                >
                  <CasinoPlayerChip actor={null} empty size={compact ? 28 : 36} />
                  <span className="casino-felt-bot-label">+ бот</span>
                </button>
              );
            }
            return (
              <span key={index} className={`casino-felt-seat${empty ? " is-empty" : ""}`}>
                <CasinoPlayerChip
                  actor={player ?? null}
                  empty={empty}
                  size={compact ? 28 : 36}
                  linked={player ? (player.participant_kind || "player") !== "bot" && player.user_id !== 0 : true}
                />
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function roomStatusLabel(room: CasinoRoomSnapshot): string {
  if (room.status === "countdown") return "игра начинается";
  if (room.status === "locked") return "спин";
  if (room.status === "settled") return "готово";
  if (room.status === "refunded") return "отмена";
  return `${room.filled}/${room.seat_count}`;
}

export function mergeRoomSpinPayload(
  live: CasinoRoomSnapshot | null,
  payload: {
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
  },
  fallbackId: string,
): CasinoRoomSnapshot {
  return {
    success: true,
    room_id: String(payload.room_id || live?.room_id || fallbackId),
    status: "locked",
    creator_id: live?.creator_id || 0,
    commit_hash: String(payload.commit_hash || live?.commit_hash || ""),
    server_seed: payload.server_seed ?? live?.server_seed ?? null,
    hmac_message: String(payload.hmac_message || live?.hmac_message || ""),
    algorithm: live?.algorithm || "hmac-sha256-commit-reveal",
    closes_at: null,
    countdown_ends_at: null,
    stake_rub: Number(payload.stake_rub) || live?.stake_rub || 0,
    seat_count: Number(payload.seat_count) || live?.seat_count || payload.players?.length || 0,
    filled: payload.players?.length || live?.filled || 0,
    pot_rub: Number(payload.pot_rub) || live?.pot_rub || 0,
    rake_percent: Number(payload.rake_percent) || live?.rake_percent || 5,
    rake_rub: payload.rake_rub ?? live?.rake_rub ?? null,
    payout_rub: payload.payout_rub ?? live?.payout_rub ?? null,
    winner_id: payload.winner_id ?? live?.winner_id ?? null,
    winner_index: payload.winner_index ?? live?.winner_index ?? null,
    players: payload.players || live?.players || [],
    my_seat: live?.my_seat ?? null,
    my_amount_rub: live?.my_amount_rub,
    my_chance_pct: live?.my_chance_pct,
    min_bet_rub: live?.min_bet_rub || 10,
    max_bet_rub: live?.max_bet_rub || 100000,
    max_seats: live?.max_seats || 10,
    collect_seconds: live?.collect_seconds || 600,
    enabled: true,
  };
}
