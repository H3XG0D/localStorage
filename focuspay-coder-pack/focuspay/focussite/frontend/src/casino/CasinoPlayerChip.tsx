import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { CasinoChatActor, CasinoDuelCard } from "@/lib/public";
import { casinoTo } from "./casinoPaths";
import { casinoDefaultAvatarUrl } from "./defaultAvatar";
import { CASINO_CATALOG } from "./gameCatalog";

export type ChipActor = Pick<CasinoChatActor, "user_id" | "display_name" | "initial"> & {
  avatar_url?: string | null;
};

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

export function CasinoPlayerAvatar({
  actor,
  size = 32,
  className = "casino-player-avatar-img",
}: {
  actor: ChipActor | null;
  size?: number;
  className?: string;
}) {
  const ident = actor ? casinoDefaultAvatarUrl(actor.user_id) : null;
  const primary = actor?.avatar_url || ident;
  const [mode, setMode] = useState<"primary" | "ident" | "letter">("primary");
  useEffect(() => {
    setMode("primary");
  }, [actor?.avatar_url, actor?.user_id]);
  const box = { width: size, height: size };
  let face;
  if (mode === "primary" && primary) {
    face = (
      <img
        src={primary}
        alt=""
        width={size}
        height={size}
        className={className}
        data-casino-ident={primary === ident ? "" : undefined}
        onError={() => setMode(ident && primary !== ident ? "ident" : "letter")}
      />
    );
  } else if (mode === "ident" && ident) {
    face = (
      <img
        src={ident}
        alt=""
        width={size}
        height={size}
        className={className}
        data-casino-ident=""
        onError={() => setMode("letter")}
      />
    );
  } else {
    face = (
      <span className="casino-player-avatar-fallback" style={box}>
        {actor?.initial || "?"}
      </span>
    );
  }
  return (
    <span className="casino-player-avatar" style={box}>
      {face}
    </span>
  );
}

export function CasinoPlayerChip({
  actor,
  empty = false,
  size = 32,
  linked = true,
}: {
  actor: ChipActor | null;
  empty?: boolean;
  size?: number;
  linked?: boolean;
}) {
  if (empty || !actor) {
    return (
      <span className="casino-player-chip is-empty" aria-label="Пустое место">
        <span className="casino-player-avatar-fallback is-silhouette" style={{ width: size, height: size }} />
      </span>
    );
  }
  const inner = (
    <>
      <CasinoPlayerAvatar actor={actor} size={size} />
      <span className="casino-player-nick">{actor.display_name}</span>
    </>
  );
  if (!linked || !actor.user_id) {
    return <span className="casino-player-chip">{inner}</span>;
  }
  return (
    <Link
      to={casinoTo(`/casino/u/${actor.user_id}`)}
      className="casino-player-chip"
      onClick={(event) => event.stopPropagation()}
    >
      {inner}
    </Link>
  );
}

export function CasinoDuelMatchRow({
  duel,
  mine,
  busy,
  onOpen,
  onJoin,
  onCancel,
}: {
  duel: CasinoDuelCard;
  mine: boolean;
  busy?: boolean;
  onOpen: () => void;
  onJoin: () => void;
  onCancel?: () => void;
}) {
  const game = CASINO_CATALOG.find((item) => item.id === duel.game_type);
  const waitingMine = mine && !duel.opponent_occupied;
  return (
    <div className="casino-duel-row-card casino-duel-match" data-casino-duel={duel.game_id}>
      <div className="casino-duel-vs">
        <CasinoPlayerChip actor={duel.creator ?? null} />
        <span className="casino-duel-vs-mark">vs</span>
        <CasinoPlayerChip actor={duel.opponent ?? null} empty={!duel.opponent_occupied} />
      </div>
      <span className="casino-duel-money">
        <strong>{formatRub(duel.bet_rub)}</strong>
        {game ? (
          <span className="casino-muted">
            {game.emoji} {game.name}
          </span>
        ) : null}
      </span>
      {waitingMine && onCancel ? (
        <button type="button" className="casino-btn casino-btn-ghost" disabled={busy} onClick={onCancel}>
          Отменить
        </button>
      ) : mine || duel.opponent_occupied ? (
        <button type="button" className="casino-btn casino-btn-ghost" onClick={onOpen}>
          Стол
        </button>
      ) : (
        <button type="button" className="casino-btn" disabled={busy} onClick={onJoin}>
          Войти
        </button>
      )}
    </div>
  );
}
