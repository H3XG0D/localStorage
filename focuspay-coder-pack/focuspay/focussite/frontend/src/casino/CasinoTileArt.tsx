import type { ReactNode } from "react";
import { ROULETTE_WHEEL_ORDER, roulettePocketColor } from "./roulette";

/** Near-black tile illustrations. White accent like the homepage; no ice-blue. */

function TileSvg({ children }: { children: ReactNode }) {
  return (
    <svg className="casino-tile-art-svg" viewBox="0 0 160 140" fill="none" aria-hidden>
      {children}
    </svg>
  );
}

function DiceArt() {
  return (
    <TileSvg>
      <ellipse cx="80" cy="118" rx="46" ry="8" fill="#000" opacity="0.35" />
      <g transform="translate(18 34) rotate(-18 36 36)">
        <rect x="10" y="10" width="72" height="72" rx="14" fill="#141414" stroke="#f4f4f5" strokeWidth="2" />
        <circle cx="32" cy="32" r="5" fill="#f4f4f5" />
        <circle cx="60" cy="32" r="5" fill="#f4f4f5" />
        <circle cx="32" cy="60" r="5" fill="#f4f4f5" />
        <circle cx="60" cy="60" r="5" fill="#f4f4f5" />
      </g>
      <g transform="translate(70 18) rotate(16 36 36)">
        <rect x="10" y="10" width="72" height="72" rx="14" fill="#1c1c1c" stroke="#e4e4e7" strokeWidth="2" />
        <circle cx="46" cy="46" r="7" fill="#f0f0f0" />
      </g>
    </TileSvg>
  );
}

function CardFanArt({ ranks }: { ranks: [string, string] }) {
  return (
    <TileSvg>
      <ellipse cx="80" cy="108" rx="54" ry="14" fill="#111" />
      <ellipse cx="80" cy="108" rx="50" ry="11" fill="#181818" stroke="#333" />
      <g transform="translate(38 22) rotate(-22)">
        <rect width="50" height="74" rx="8" fill="#f4f4f5" stroke="#2a2a2a" />
        <text x="9" y="22" fill="#0c0c0c" fontSize="16" fontFamily="ui-monospace, monospace" fontWeight="700">
          {ranks[0]}
        </text>
      </g>
      <g transform="translate(74 16) rotate(18)">
        <rect width="50" height="74" rx="8" fill="#f4f4f5" stroke="#2a2a2a" />
        <text x="9" y="22" fill="#e5484d" fontSize="16" fontFamily="ui-monospace, monospace" fontWeight="700">
          {ranks[1]}
        </text>
      </g>
    </TileSvg>
  );
}

function HoldemArt() {
  return (
    <TileSvg>
      <ellipse cx="80" cy="86" rx="62" ry="28" fill="#141414" stroke="#333" />
      <rect x="22" y="48" width="22" height="34" rx="3" fill="#f4f4f5" />
      <rect x="48" y="44" width="22" height="34" rx="3" fill="#f4f4f5" />
      <rect x="74" y="44" width="22" height="34" rx="3" fill="#f4f4f5" />
      <rect x="100" y="48" width="22" height="34" rx="3" fill="#111" stroke="#f4f4f5" />
      <rect x="126" y="50" width="12" height="32" rx="3" fill="#111" stroke="#f4f4f5" />
      <rect x="54" y="90" width="20" height="30" rx="3" fill="#111" stroke="#f4f4f5" transform="rotate(-12 54 90)" />
      <rect x="88" y="88" width="20" height="30" rx="3" fill="#111" stroke="#f4f4f5" transform="rotate(12 88 88)" />
    </TileSvg>
  );
}

function WheelArt({ ticks }: { ticks: number }) {
  const marks = Array.from({ length: ticks }, (_, i) => {
    const a = (i / ticks) * Math.PI * 2 - Math.PI / 2;
    const x1 = 80 + Math.cos(a) * 28;
    const y1 = 62 + Math.sin(a) * 28;
    const x2 = 80 + Math.cos(a) * 42;
    const y2 = 62 + Math.sin(a) * 42;
    return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#f4f4f5" strokeWidth="2" />;
  });
  return (
    <TileSvg>
      <circle cx="80" cy="62" r="46" fill="#111" stroke="#2a2a2a" strokeWidth="2" />
      <circle cx="80" cy="62" r="42" fill="#141414" stroke="#f4f4f5" strokeWidth="2" />
      {marks}
      <circle cx="80" cy="62" r="12" fill="#181818" stroke="#e4e4e7" />
      <circle cx="80" cy="62" r="4" fill="#f4f4f5" />
    </TileSvg>
  );
}

/** Single-zero wheel: red/black alternation of the real sector order, zero in green. */
function RouletteArt() {
  const sectors = ROULETTE_WHEEL_ORDER.map((pocket, index) => {
    const step = 360 / ROULETTE_WHEEL_ORDER.length;
    const from = ((index - 0.5) * step - 90) * (Math.PI / 180);
    const to = ((index + 0.5) * step - 90) * (Math.PI / 180);
    const point = (r: number, a: number) => `${(80 + Math.cos(a) * r).toFixed(2)} ${(62 + Math.sin(a) * r).toFixed(2)}`;
    const color = roulettePocketColor(pocket);
    return (
      <path
        key={pocket}
        d={`M ${point(46, from)} A 46 46 0 0 1 ${point(46, to)} L ${point(26, to)} A 26 26 0 0 0 ${point(26, from)} Z`}
        fill={color === "red" ? "#b52d2b" : color === "green" ? "#147a52" : "#151515"}
      />
    );
  });
  return (
    <TileSvg>
      <circle cx="80" cy="62" r="49" fill="#0f0f0f" stroke="#2a2a2a" strokeWidth="2" />
      {sectors}
      <circle cx="80" cy="62" r="26" fill="#141414" stroke="#f4f4f5" strokeWidth="1.5" />
      <circle cx="80" cy="62" r="8" fill="#1c1c1c" stroke="#e4e4e7" />
      <circle cx="80" cy="18" r="3.5" fill="#f0f0f0" />
    </TileSvg>
  );
}

function NardyArt() {
  const points = [];
  for (let i = 0; i < 6; i += 1) {
    const x = 34 + i * 16;
    points.push(
      <polygon key={`t${i}`} points={`${x},28 ${x + 14},28 ${x + 7},58`} fill={i % 2 ? "#3a3a3a" : "#1a1a1a"} />,
      <polygon key={`b${i}`} points={`${x},112 ${x + 14},112 ${x + 7},82`} fill={i % 2 ? "#1a1a1a" : "#3a3a3a"} />,
    );
  }
  return (
    <TileSvg>
      <rect x="26" y="22" width="108" height="96" rx="8" fill="#101010" stroke="#f4f4f5" strokeWidth="2" />
      <rect x="76" y="28" width="4" height="84" fill="#3a3a3a" />
      {points}
      <circle cx="123" cy="40" r="5" fill="#f4f4f5" />
      <circle cx="123" cy="52" r="5" fill="#f4f4f5" />
      <circle cx="41" cy="96" r="5" fill="#141414" stroke="#f4f4f5" strokeWidth="1.5" />
      <circle cx="41" cy="84" r="5" fill="#141414" stroke="#f4f4f5" strokeWidth="1.5" />
    </TileSvg>
  );
}

function DraughtsArt() {
  const cells = [];
  for (let row = 0; row < 8; row += 1) {
    for (let col = 0; col < 8; col += 1) {
      const dark = (col + row) % 2 === 1;
      cells.push(
        <rect
          key={`${col}-${row}`}
          x={28 + col * 13}
          y={18 + row * 13}
          width="13"
          height="13"
          fill={dark ? "#1a1a1a" : "#3a3a3a"}
        />,
      );
    }
  }
  return (
    <TileSvg>
      <rect x="26" y="16" width="108" height="108" rx="6" fill="#101010" stroke="#f4f4f5" strokeWidth="2" />
      {cells}
      <circle cx="47" cy="89" r="5" fill="#f4f4f5" />
      <circle cx="73" cy="63" r="5" fill="#f4f4f5" />
      <circle cx="99" cy="37" r="5" fill="#141414" stroke="#f4f4f5" strokeWidth="1.5" />
    </TileSvg>
  );
}

export function CasinoTileArt({ gameId }: { gameId: string }) {
  switch (gameId) {
    case "pvp_dice":
      return <DiceArt />;
    case "baccara":
      return <CardFanArt ranks={["A", "9"]} />;
    case "blackjack":
      return <CardFanArt ranks={["A", "K"]} />;
    case "holdem":
      return <HoldemArt />;
    case "roulette":
      return <RouletteArt />;
    case "raffle":
      return <WheelArt ticks={12} />;
    case "jackpot":
      return <WheelArt ticks={8} />;
    case "fixed_room":
      return <WheelArt ticks={6} />;
    case "clan_war":
      return <DiceArt />;
    case "russian_draughts":
      return <DraughtsArt />;
    case "nardy":
      return <NardyArt />;
    default:
      return null;
  }
}
