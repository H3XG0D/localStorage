import { useEffect, useState } from "react";

export type CasinoSuitId = "spades" | "hearts" | "diamonds" | "clubs";

const SUITS: Record<string, { id: CasinoSuitId; red: boolean }> = {
  "♠": { id: "spades", red: false },
  "♥": { id: "hearts", red: true },
  "♦": { id: "diamonds", red: true },
  "♣": { id: "clubs", red: false },
};

const SUIT_PATHS: Record<string, string> = {
  "♦": "M50 0 100 50 50 100 0 50Z",
  "♥": "M50 94C42 85 0 53 0 27C0 -2 34 -9 50 17C66 -9 100 -2 100 27C100 53 58 85 50 94Z",
  "♠": "M50 0C41 12 0 43 0 65C0 88 29 96 44 76L35 100H65L56 76C71 96 100 88 100 65C100 43 59 12 50 0Z",
  "♣": "M50 0C27 0 19 23 33 40C5 31 -11 61 8 79C20 91 35 86 44 76L35 100H65L56 76C65 86 80 91 92 79C111 61 95 31 67 40C81 23 73 0 50 0Z",
};

export function parsePlayingCard(code: string | null | undefined): {
  code: string;
  rank: string;
  suit: CasinoSuitId;
  suitGlyph: string;
  red: boolean;
} | null {
  const text = String(code || "").trim();
  if (text.length < 2) return null;
  const suitGlyph = text.slice(-1);
  const suit = SUITS[suitGlyph];
  const rank = text.slice(0, -1);
  if (!suit || !rank) return null;
  return { code: text, rank, suit: suit.id, suitGlyph, red: suit.red };
}

function reduceCardMotion(): boolean {
  if (typeof document === "undefined") return false;
  if (document.documentElement.classList.contains("casino-reduce-motion")) return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function CardFace({
  rank,
  suitGlyph,
  red,
}: {
  rank: string;
  suitGlyph: string;
  red: boolean;
}) {
  const path = SUIT_PATHS[suitGlyph];
  const suitY = suitGlyph === "♥" ? 105.5 : 93.5;
  return (
    <svg viewBox="0 0 207 307" className="casino-playing-card-art" aria-hidden>
      <rect width="207" height="307" rx="20" fill="var(--accent)" />
      <g fill={red ? "var(--lose)" : "var(--ink)"}>
        <text
          x="23"
          y="85"
          fontFamily="Inter, Arial, sans-serif"
          fontWeight="700"
          fontSize={rank === "10" ? "68" : "80"}
          letterSpacing="-3"
        >
          {rank}
        </text>
        {path ? (
          <svg x="43.5" y={suitY} width="120" height="120" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
            <path d={path} />
          </svg>
        ) : null}
      </g>
    </svg>
  );
}

export function CasinoPlayingCard({
  code,
  faceDown = false,
  dealing = false,
  compact = false,
}: {
  code?: string | null;
  faceDown?: boolean;
  dealing?: boolean;
  compact?: boolean;
}) {
  const parsed = faceDown ? null : parsePlayingCard(code);
  const [flipped, setFlipped] = useState(false);
  useEffect(() => {
    if (!parsed) {
      setFlipped(false);
      return;
    }
    if (reduceCardMotion()) {
      setFlipped(true);
      return;
    }
    const timer = window.setTimeout(() => setFlipped(true), 80);
    return () => window.clearTimeout(timer);
  }, [parsed?.code, faceDown]);

  const sizeClass = compact ? " is-compact" : "";
  const revealed = Boolean(parsed && flipped);
  return (
    <div
      className={`casino-playing-card${parsed?.red ? " is-red" : ""}${parsed && !parsed.red ? " is-black" : ""}${sizeClass}${dealing ? " is-dealing" : ""}${revealed ? " is-revealed" : ""}`}
      data-casino-card={parsed ? parsed.code : "back"}
      data-rank={parsed?.rank}
      data-suit={parsed?.suit}
      title={parsed?.code}
      role={parsed ? undefined : "img"}
      aria-label={parsed ? undefined : "Закрытая карта"}
      aria-hidden={parsed ? true : undefined}
    >
      <div className="casino-playing-card-flip">
        <div className="casino-playing-card-back">
          <img src="/casino/baccarat-card-back.svg" alt="" draggable={false} />
        </div>
        <div className="casino-playing-card-front">
          {parsed ? <CardFace rank={parsed.rank} suitGlyph={parsed.suitGlyph} red={parsed.red} /> : null}
        </div>
      </div>
    </div>
  );
}
