import { useEffect, useRef, useState } from "react";
import { CasinoRoundedDie } from "./CasinoRoundedDie";

const FACE_DOTS: Record<number, number[]> = {
  1: [5],
  2: [1, 9],
  3: [1, 5, 9],
  4: [1, 3, 7, 9],
  5: [1, 3, 5, 7, 9],
  6: [1, 3, 4, 6, 7, 9],
};

export function prefersCasinoReducedMotion(): boolean {
  if (typeof document === "undefined") return false;
  if (document.documentElement.classList.contains("casino-reduce-motion")) return true;
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

const DIE_FACE: Record<number, { rx: number; ry: number }> = {
  1: { rx: 0, ry: 0 },
  2: { rx: 0, ry: -90 },
  3: { rx: -90, ry: 0 },
  4: { rx: 90, ry: 0 },
  5: { rx: 0, ry: 90 },
  6: { rx: 0, ry: 180 },
};

export function asDiePips(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  const pips = Math.trunc(value);
  return pips >= 1 && pips <= 6 ? pips : null;
}

export function CasinoDie({
  value,
  rolling = false,
  seat,
  label,
}: {
  value: number | null;
  rolling?: boolean;
  seat?: string;
  label?: string;
}) {
  const pips = asDiePips(value);
  const pending = pips == null;
  const shownPips = pips ?? 1;
  const [shown, setShown] = useState(shownPips);
  const [settling, setSettling] = useState(false);
  const [webglOk, setWebglOk] = useState(true);
  const skipSpin = useRef(true);
  const volume = webglOk && !prefersCasinoReducedMotion() && (rolling || !pending);
  const face = DIE_FACE[shown] ?? DIE_FACE[1];
  const rotation = rolling ? { rx: face.rx + 720, ry: face.ry - 540 } : face;

  useEffect(() => {
    if (rolling) return;
    const next = asDiePips(value) ?? 1;
    setShown(next);
    if (skipSpin.current) {
      skipSpin.current = false;
      return;
    }
    if (prefersCasinoReducedMotion()) return;
    setSettling(true);
    const timer = window.setTimeout(() => setSettling(false), 700);
    return () => window.clearTimeout(timer);
  }, [rolling, value]);

  const dots = FACE_DOTS[shown] ?? FACE_DOTS[1];

  return (
    <div className="casino-die-block">
      {label ? <span className="casino-die-caption">{label}</span> : null}
      <div
        className={`casino-die${rolling ? " is-rolling" : ""}${settling ? " is-settling" : ""}${pending && !rolling ? " is-pending" : ""}`}
        data-casino-die={seat || ""}
        data-value={rolling || pending ? "" : String(shown)}
        data-pips={rolling || pending ? "" : String(shown)}
        data-pending={pending && !rolling ? "1" : "0"}
        aria-hidden
      >
        {volume ? (
          <CasinoRoundedDie rotation={rotation} duration={700} onUnavailable={() => setWebglOk(false)} />
        ) : (
          <div className="casino-die-face" data-face={shown}>
            <span className="casino-die-pips">
              {Array.from({ length: 9 }, (_, index) => (
                <i key={index} className={dots.includes(index + 1) ? "is-on" : ""} />
              ))}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export function CasinoDiceDuel({
  leftLabel,
  rightLabel,
  leftValue,
  rightValue,
  leftRolling,
  rightRolling,
  leftSeat = "player",
  rightSeat = "house",
}: {
  leftLabel: string;
  rightLabel: string;
  leftValue: number | null;
  rightValue: number | null;
  leftRolling?: boolean;
  rightRolling?: boolean;
  leftSeat?: "player" | "house" | "creator" | "opponent";
  rightSeat?: "player" | "house" | "creator" | "opponent";
}) {
  return (
    <div className="casino-dice-duel" data-casino-dice-duel="">
      <CasinoDie value={leftValue} rolling={leftRolling} seat={leftSeat} label={leftLabel} />
      <span className="casino-dice-vs" aria-hidden>
        vs
      </span>
      <CasinoDie value={rightValue} rolling={rightRolling} seat={rightSeat} label={rightLabel} />
    </div>
  );
}

export function CasinoDiceTable({
  players,
  house,
  rolling = false,
}: {
  players: Array<{ label: string; value: number | null }>;
  house: Array<{ label: string; value: number | null }>;
  rolling?: boolean;
}) {
  return (
    <div className="casino-dice-table" data-casino-house-dice="">
      <div className="casino-dice-table-row" data-casino-house-dice-players="">
        {players.map((item, index) => (
          <CasinoDie
            key={`p-${item.label}-${index}`}
            value={item.value}
            rolling={rolling}
            seat="player"
            label={item.label}
          />
        ))}
      </div>
      <span className="casino-dice-vs" aria-hidden>
        vs
      </span>
      <div className="casino-dice-table-row" data-casino-house-dice-house="">
        {house.map((item, index) => (
          <CasinoDie
            key={`h-${item.label}-${index}`}
            value={item.value}
            rolling={rolling}
            seat="house"
            label={item.label}
          />
        ))}
      </div>
    </div>
  );
}
