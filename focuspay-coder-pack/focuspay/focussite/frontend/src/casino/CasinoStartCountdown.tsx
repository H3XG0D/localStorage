import { useEffect, useState } from "react";

const WINDOW_SEC = 10;

export function countdownLeftSec(endsAt: string | null | undefined, nowMs = Date.now()): number | null {
  if (!endsAt) return null;
  const end = Date.parse(endsAt);
  if (!Number.isFinite(end)) return null;
  const left = Math.ceil((end - nowMs) / 1000);
  if (left <= 0 || left > WINDOW_SEC) return null;
  return left;
}

export function CasinoStartCountdown({
  endsAt,
  label = "Игра начинается",
  ring = false,
}: {
  endsAt?: string | null;
  label?: string;
  ring?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!endsAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, [endsAt]);
  const left = countdownLeftSec(endsAt, now);
  if (left == null) return null;
  if (ring) {
    const radius = 20;
    const circumference = 2 * Math.PI * radius;
    return (
      <div className="casino-dice-timer" data-casino-countdown={left} role="timer" aria-label={`${label} через ${left} секунд`}>
        <svg className="casino-dice-timer-svg" viewBox="0 0 48 48" aria-hidden>
          <circle className="casino-dice-timer-track" cx="24" cy="24" r={radius} />
          <circle
            className="casino-dice-timer-value"
            cx="24"
            cy="24"
            r={radius}
            style={{ strokeDasharray: circumference, strokeDashoffset: circumference * (1 - left / WINDOW_SEC) }}
          />
        </svg>
        <span>{left}</span>
      </div>
    );
  }
  return (
    <div className="casino-start-countdown" data-casino-countdown={left} role="status">
      <span>{label}</span>
      <strong>{left}</strong>
    </div>
  );
}
