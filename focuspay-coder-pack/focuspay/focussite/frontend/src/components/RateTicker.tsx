// Live rates marquee. Shows each asset's market price with a ▲/▼ direction mark
// and a brief highlight pulse when the value changes. Auto-scrolls, pauses on
// hover, and stops moving under reduced motion.
import { useEffect, useRef, useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import { CRYPTO_META, type CryptoId, type RatesResponse } from "@/lib/public";
import { cn, formatMoney } from "@/lib/utils";

const ASSETS: CryptoId[] = ["usdt", "btc", "ltc", "trx"];

type Dir = "up" | "down" | "flat";

function Chip({ id, price, dir, pulse }: { id: CryptoId; price: number | undefined; dir: Dir; pulse: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-colors duration-500",
        pulse ? "border-foreground/40 bg-muted" : "border-border bg-card",
      )}
    >
      <span className="font-semibold">{CRYPTO_META[id].label}</span>
      <span className="font-mono text-muted-foreground">{price ? `${formatMoney(price)} ₽` : "…"}</span>
      {dir !== "flat" &&
        (dir === "up" ? (
          <TrendingUp className="size-3 text-foreground" />
        ) : (
          <TrendingDown className="size-3 text-muted-foreground" />
        ))}
    </span>
  );
}

export function RateTicker({ rates }: { rates: RatesResponse | null }) {
  const reduce = useReducedMotion();
  const prev = useRef<Record<string, number>>({});
  const [dirs, setDirs] = useState<Record<string, Dir>>({});
  const [pulse, setPulse] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!rates) return;
    const nextDirs: Record<string, Dir> = {};
    const nextPulse: Record<string, boolean> = {};
    for (const id of ASSETS) {
      const p = rates.rates?.[id]?.market;
      if (p == null) continue;
      const old = prev.current[id];
      if (old != null && p !== old) {
        nextDirs[id] = p > old ? "up" : "down";
        nextPulse[id] = true;
      } else {
        nextDirs[id] = dirs[id] || "flat";
      }
      prev.current[id] = p;
    }
    setDirs((d) => ({ ...d, ...nextDirs }));
    if (Object.keys(nextPulse).length) {
      setPulse(nextPulse);
      const t = window.setTimeout(() => setPulse({}), 900);
      return () => window.clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rates]);

  const chips = ASSETS.map((id) => (
    <Chip key={id} id={id} price={rates?.rates?.[id]?.market} dir={dirs[id] || "flat"} pulse={!!pulse[id]} />
  ));

  // Static row under reduced motion; marquee otherwise.
  if (reduce) return <div className="flex flex-wrap gap-2">{chips}</div>;

  return (
    <div className="group relative w-full min-w-0 max-w-full overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)]">
      <div className="flex w-max gap-2 animate-[ticker_22s_linear_infinite] group-hover:[animation-play-state:paused]">
        {chips}
        {chips /* duplicate for seamless loop */}
      </div>
    </div>
  );
}
