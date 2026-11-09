import { CircleDot, Club, Dices, Spade, Sparkles, Target, Ticket } from "lucide-react";

function strokeIcon(size: number, name: string) {
  return {
    xmlns: "http://www.w3.org/2000/svg",
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className: `lucide lucide-${name}`,
    "aria-hidden": true as const,
  };
}

function DraughtsIcon({ size }: { size: number }) {
  return (
    <svg {...strokeIcon(size, "draughts")}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M5 5h6v6H5zM13 13h6v6h-6z" fill="currentColor" stroke="none" />
    </svg>
  );
}

function NardyIcon({ size }: { size: number }) {
  return (
    <svg {...strokeIcon(size, "nardy")}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M12 4v16" />
      <path d="M5 6.5h6L8 14z" fill="currentColor" stroke="none" />
      <path d="M13 17.5h6L16 10z" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function gameRailIcon(id: string, emoji: string, size = 20) {
  const common = { size, "aria-hidden": true as const };
  if (id === "pvp_dice") return <Dices {...common} />;
  if (id === "blackjack" || id === "holdem") return <Spade {...common} />;
  if (id === "baccara") return <Club {...common} />;
  if (id === "jackpot") return <Sparkles {...common} />;
  if (id === "roulette") return <CircleDot {...common} />;
  if (id === "raffle") return <Ticket {...common} />;
  if (id === "fixed_room") return <Target {...common} />;
  if (id === "russian_draughts") return <DraughtsIcon size={size} />;
  if (id === "nardy") return <NardyIcon size={size} />;
  return (
    <span className="casino-rail-emoji" aria-hidden>
      {emoji}
    </span>
  );
}
